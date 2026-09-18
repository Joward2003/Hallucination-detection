from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from credit_review.domain.errors import CheckpointError, ConflictError
from credit_review.knowledge_base import KnowledgeBaseRepository


class KnowledgeBaseRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = {"schema_version": "knowledge-base-v1", "manifest": {"status": "READY", "document_count": 1}, "evidence": []}

    def test_staging_publish_and_active_load_are_atomic_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = KnowledgeBaseRepository(directory)
            repository.save_staging("kb-finance", "v1", self.snapshot)
            self.assertEqual(repository.list_versions("kb-finance"), ["v1"])
            published = repository.publish("kb-finance", "v1")
            self.assertEqual(published["version"], "v1")
            self.assertEqual(repository.active_version("kb-finance"), "v1")
            self.assertEqual(repository.load("kb-finance")["manifest"]["status"], "READY")

    def test_compare_and_swap_keeps_old_active_version_on_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = KnowledgeBaseRepository(directory)
            repository.save_staging("kb", "v1", self.snapshot)
            repository.publish("kb", "v1")
            repository.save_staging("kb", "v2", self.snapshot)
            with self.assertRaises(ConflictError):
                repository.publish("kb", "v2", expected_active_version="v0")
            self.assertEqual(repository.active_version("kb"), "v1")
            with self.assertRaises(CheckpointError):
                repository.load("kb", "missing")

    def test_path_components_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = KnowledgeBaseRepository(directory)
            with self.assertRaises(ValueError):
                repository.save_staging("../escape", "v1", self.snapshot)

    def test_staging_same_version_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = KnowledgeBaseRepository(directory)
            first = {"manifest": {"status": "READY"}, "evidence": [{"evidence_id": "E1"}]}
            second = {"manifest": {"status": "READY"}, "evidence": [{"evidence_id": "E2"}]}
            repository.save_staging("kb", "v1", first)
            self.assertEqual(repository.save_staging("kb", "v1", first).name, "v1.json")
            with self.assertRaises(ConflictError):
                repository.save_staging("kb", "v1", second)


if __name__ == "__main__":
    unittest.main()
