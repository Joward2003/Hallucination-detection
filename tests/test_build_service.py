from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from credit_review.domain.errors import ConflictError
from credit_review.knowledge_base import BuildManager, KnowledgeBaseRepository


class BuildManagerTests(unittest.TestCase):
    def _payload(self, **overrides):
        payload = {
            "kb_id": "finance",
            "tenant_id": "tenant-a",
            "requested_by": "u1",
            "idempotency_key": "same",
            "kb_version": "2024-v1",
            "source": {"content_list": [{"type": "table", "text": "甲公司2024年流动比率为1.5。", "page_idx": 0}]},
        }
        payload.update(overrides)
        return payload

    def test_one_click_build_runs_stages_and_publishes_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = BuildManager(KnowledgeBaseRepository(directory))
            record = manager.create(self._payload())
            self.assertEqual(record["status"], "READY")
            self.assertEqual(record["active_version"], "2024-v1")
            self.assertEqual(manager.load_active("finance")["document_version"], "2024-v1")
            self.assertEqual(record["stages"][0]["status"], "VALIDATING")
            self.assertEqual(record["stages"][-1]["status"], "PUBLISHING")
            self.assertEqual(
                [stage["status"] for stage in record["stages"]],
                ["VALIDATING", "PARSING", "ENRICHING", "INDEXING", "CHECKING", "PUBLISHING"],
            )

    def test_duplicate_click_is_idempotent_and_failure_is_queryable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = BuildManager(KnowledgeBaseRepository(directory))
            first = manager.create(self._payload())
            second = manager.create(self._payload())
            self.assertEqual(first["build_id"], second["build_id"])
            failed = manager.create(self._payload(idempotency_key="bad", source={"content_list": []}))
            self.assertEqual(failed["status"], "FAILED")
            self.assertTrue(failed["errors"])

    def test_same_idempotency_key_with_different_request_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = BuildManager(KnowledgeBaseRepository(directory))
            manager.create(self._payload())
            with self.assertRaises(ConflictError):
                manager.create(self._payload(source={"content_list": [{"type": "text", "text": "不同材料。"}]}))

    def test_index_builder_runs_before_snapshot_is_published(self) -> None:
        calls = []

        def index_builder(kb_id, version, snapshot):
            calls.append((kb_id, version, snapshot["manifest"]["status"]))
            return {"dense_index_ref": f"indexes/{kb_id}/{version}/dense.json", "bm25_index_ref": f"indexes/{kb_id}/{version}/bm25s"}

        with tempfile.TemporaryDirectory() as directory:
            manager = BuildManager(KnowledgeBaseRepository(directory), index_builder=index_builder)
            record = manager.create(self._payload())
            self.assertEqual(calls, [("finance", "2024-v1", "READY")])
            self.assertEqual(record["manifest"]["dense_index_ref"], "indexes/finance/2024-v1/dense.json")

    def test_cancel_ready_build_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = BuildManager(KnowledgeBaseRepository(directory))
            record = manager.create(self._payload())
            with self.assertRaises(ConflictError):
                manager.cancel(record["build_id"])


if __name__ == "__main__":
    unittest.main()
