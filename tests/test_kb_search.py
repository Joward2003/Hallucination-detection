from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from credit_review.knowledge_base import BuildManager, KnowledgeBaseRepository, KnowledgeBaseSearchService


class KnowledgeBaseSearchTests(unittest.TestCase):
    def _source(self, value: str):
        return {"content_list": [{"type": "table", "text": f"甲公司2024年流动比率为{value}。", "page_idx": 0}]}

    def _payload(self, version: str, value: str, key: str, **extra):
        payload = {"kb_id": "finance", "tenant_id": "t", "requested_by": "u", "idempotency_key": key, "kb_version": version, "source": self._source(value)}
        payload.update(extra)
        return payload

    def test_active_search_follows_publish_and_pinned_search_stays_on_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = KnowledgeBaseRepository(directory)
            builds = BuildManager(repository)
            builds.create(self._payload("v1", "1.5", "k1"))
            builds.create(self._payload("v2", "2.0", "k2", expected_active_version="v1"))
            query = {"query_id": "Q1", "query_text": "甲公司 2024 流动比率", "retrieval_profile": "financial_table", "metric_ids": ["current_ratio"], "periods": ["2024"]}
            active = KnowledgeBaseSearchService(repository, "finance").retrieve(query)
            pinned = KnowledgeBaseSearchService(repository, "finance", version="v1").retrieve(query)
            self.assertIn("2.0", active[0]["content"])
            self.assertEqual(active[0]["kb_version"], "v2")
            self.assertIn("1.5", pinned[0]["content"])
            self.assertEqual(pinned[0]["kb_version"], "v1")

    def test_service_pins_active_version_for_follow_up_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = KnowledgeBaseRepository(directory)
            builds = BuildManager(repository)
            builds.create(self._payload("v1", "1.5", "k1"))
            service = KnowledgeBaseSearchService(repository, "finance")
            query = {"query_text": "甲公司 2024 流动比率", "retrieval_profile": "financial_table", "metric_ids": ["current_ratio"], "periods": ["2024"]}
            self.assertIn("1.5", service.retrieve(query)[0]["content"])
            builds.create(self._payload("v2", "2.0", "k2", expected_active_version="v1"))
            self.assertIn("1.5", service.retrieve(query)[0]["content"])


if __name__ == "__main__":
    unittest.main()
