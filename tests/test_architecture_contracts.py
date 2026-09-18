from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from credit_review.agents.critic_verifier import CriticVerifier
from credit_review.config.models import RetrievalConfig
from credit_review.config.settings import Settings
from credit_review.domain.errors import CheckpointError
from credit_review.graph.routes import route_after_compare, route_after_grading
from credit_review.infrastructure.checkpoints import InMemoryCheckpointStore
from credit_review.observability.audit import InMemoryAuditSink
from credit_review.security.redaction import redact_mapping, redact_text


class ArchitectureContractTests(unittest.TestCase):
    def test_routes_are_pure_and_bound_retrieval_rewrite(self) -> None:
        self.assertEqual(route_after_grading({"evidence_status": "INSUFFICIENT", "retry_count": 0}), "rewrite_query")
        self.assertEqual(route_after_grading({"evidence_status": "INSUFFICIENT", "retry_count": 1}), "verify")
        self.assertEqual(route_after_compare({"initial_verdict": {"status": "SUPPORTED"}, "critic_verdict": {"status": "CONTRADICTED"}}), "human")

    def test_critic_surface_does_not_require_initial_verdict(self) -> None:
        critic = CriticVerifier()
        result = critic.verify_independently({"fact": "事实"}, {"parent_text": "事实"}, [], [], "INSUFFICIENT")
        self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE")

    def test_checkpoint_is_copy_isolated_and_missing_is_explicit(self) -> None:
        store = InMemoryCheckpointStore()
        state = {"items": [1]}
        store.save("thread-1", state)
        state["items"].append(2)
        self.assertEqual(store.load("thread-1")["items"], [1])
        with self.assertRaises(CheckpointError):
            store.load("missing")

    def test_audit_is_append_only_and_secrets_are_redacted(self) -> None:
        sink = InMemoryAuditSink()
        sink.append("review.created", "R1", "u1", {"status": "RUNNING"})
        sink.append("review.cancelled", "R1", "u1", {"status": "CANCELLED"})
        self.assertEqual([event["event_type"] for event in sink.list("R1")], ["review.created", "review.cancelled"])
        self.assertNotIn("abc", redact_text("api_key=abc"))
        self.assertEqual(redact_mapping({"token": "abc", "nested": {"password": "pw"}})["token"], "[REDACTED]")

    def test_settings_are_conservative_by_default(self) -> None:
        settings = Settings()
        self.assertEqual(settings.external_llm_allowed_classifications, ())
        self.assertEqual(Settings.from_env().max_retrieval_attempts, 2)
        self.assertEqual(settings.retrieval.backend, "deterministic")
        self.assertEqual(RetrievalConfig(backend="sentence_transformers").embedding_model, "BAAI/bge-m3")


if __name__ == "__main__":
    unittest.main()
