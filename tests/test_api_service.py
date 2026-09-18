from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from credit_review.api.service import ReviewManager
from credit_review.domain.errors import ConflictError
from credit_review.api.app import ReviewAPI
from credit_review.knowledge_base import BuildManager, KnowledgeBaseRepository


class ApiServiceTests(unittest.TestCase):
    def test_create_is_idempotent_per_tenant_and_key(self) -> None:
        manager = ReviewManager()
        payload = {"report_id": "report-1", "report_version": "v1", "tenant_id": "tenant-a", "project_id": "project-a", "requested_by": "u1", "idempotency_key": "same", "report_text": "公司收入增长。"}
        first = manager.create(payload)
        second = manager.create(payload)
        self.assertEqual(first["review_id"], second["review_id"])

    def test_cancel_changes_workflow_state(self) -> None:
        manager = ReviewManager(runner=lambda *args, **kwargs: {"workflow_status": "RUNNING"})
        record = manager.create({"report_id": "r", "report_version": "v1", "tenant_id": "t", "project_id": "p", "requested_by": "u", "idempotency_key": "k", "report_text": "事实。"})
        cancelled = manager.cancel(record["review_id"])
        self.assertEqual(cancelled["status"], "CANCELLED")

    def test_human_tasks_ignores_reviews_without_a_human_task(self) -> None:
        manager = ReviewManager(runner=lambda *args, **kwargs: {"workflow_status": "COMPLETED", "human_task": None})
        manager.create({"report_id": "r", "report_version": "v1", "tenant_id": "t", "project_id": "p", "requested_by": "u", "idempotency_key": "k", "report_text": "事实。"})
        self.assertEqual(manager.human_tasks(), [])

    def test_human_decision_uses_task_version_and_preserves_result_history(self) -> None:
        paused_state = {
            "workflow_status": "HUMAN_REVIEW_REQUIRED", "human_task": {"task_id": "HT-F1", "task_version": 3, "status": "PENDING"},
            "current_fact": {"fact_id": "F1", "fact": "事实"}, "current_parent": {"parent_id": "P1", "parent_text": "事实"},
            "current_queries": [], "current_evidence": [], "current_assessments": [], "current_factor": [], "verification_result": {"status": "INSUFFICIENT_EVIDENCE", "reason": "待人工", "confidence": "low"},
            "numeric_checks": [], "rule_hits": [], "risk_decision": {"next_step": "human"}, "critic_verdict": None,
            "completed_results": [], "child_index": 0, "flat_children": [{"child": {"fact_id": "F1"}}], "fact_groups": [], "company_info": None,
        }
        manager = ReviewManager(runner=lambda *args, **kwargs: paused_state)
        record = manager.create({"report_id": "r", "report_version": "v1", "tenant_id": "t", "project_id": "p", "requested_by": "u", "idempotency_key": "k", "report_text": "事实。"})
        with self.assertRaises(ConflictError):
            manager.submit_human_decision(record["review_id"], {"task_version": 2, "decision": "SUPPORTED"})
        completed = manager.submit_human_decision(record["review_id"], {"task_version": 3, "decision": "SUPPORTED", "comment": "确认", "decided_by": "reviewer"})
        self.assertEqual(completed["status"], "COMPLETED")
        self.assertEqual(completed["state"]["review_result"]["summary_counts"], {"SUPPORTED": 1})

    def test_review_api_exposes_one_click_build_and_version_listing(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            builds = BuildManager(KnowledgeBaseRepository(directory))
            api = ReviewAPI(build_manager=builds)
            record = api.create_build({
                "kb_id": "kb", "tenant_id": "t", "requested_by": "u", "idempotency_key": "k",
                "kb_version": "v1", "source": {"content_list": [{"type": "text", "text": "公司现金流改善。"}]},
            })
            self.assertEqual(api.get_build(record["build_id"])["status"], "READY")
            self.assertEqual(api.list_kb_versions("kb"), ["v1"])
            search = api.search_kb("kb", {"query": {"query_id": "Q1", "query_text": "公司现金流", "retrieval_profile": "atomic_text"}})
            self.assertEqual(search["kb_version"], "v1")
            self.assertTrue(search["hits"])


if __name__ == "__main__":
    unittest.main()
