from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from credit_review.domain.errors import DomainValidationError
from credit_review.domain.invariants import validate_fact_groups, validate_verdict
from credit_review.policies.confidence import confidence_band
from credit_review.policies.risk import RiskPolicy
from credit_review.retrieval.filters import filter_by_scope
from credit_review.retrieval.service import ScopedInMemoryRetriever
from credit_review.rules.engine import Rule, RuleEngine
from credit_review.verification.citation import citation_is_traceable, content_hash
from credit_review.verification.conflict import has_conflict
from credit_review.verification.numeric import DeterministicNumericValidator, validate_change
from credit_review.verification.sufficiency import evidence_status_from_relations


class DomainInvariantTests(unittest.TestCase):
    def test_parent_child_link_and_spans_are_checked(self) -> None:
        groups = [{"parent": {"parent_id": "P001", "parent_text": "abc", "source_start": 0, "source_end": 3}, "children": [{"fact_id": "F001", "parent_id": "P001", "fact": "abc", "source_start": 0, "source_end": 3}]}]
        validate_fact_groups(groups)
        groups[0]["children"][0]["parent_id"] = "P999"
        with self.assertRaises(DomainValidationError):
            validate_fact_groups(groups)
        groups[0]["children"][0]["parent_id"] = "P001"
        groups[0]["children"][0]["source_end"] = 4
        with self.assertRaises(DomainValidationError):
            validate_fact_groups(groups)

    def test_verdict_status_is_closed_set(self) -> None:
        validate_verdict({"status": "SUPPORTED", "confidence_band": "medium"})
        with self.assertRaises(DomainValidationError):
            validate_verdict({"status": "maybe", "confidence_band": "medium"})


class VerificationTests(unittest.TestCase):
    def test_numeric_change_is_deterministic(self) -> None:
        check = validate_change(120, 100, 20)
        self.assertTrue(check.passed)
        self.assertEqual(check.observed, Decimal("20.0"))
        self.assertFalse(validate_change(120, 100, 25).passed)

    def test_claim_is_compared_with_external_evidence(self) -> None:
        validator = DeterministicNumericValidator()
        checks = validator.validate({"fact_id": "F1", "fact": "公司2024年营业收入同比增长20%"}, [{"content": "公司2024年营业收入同比增长18%"}])
        self.assertEqual(len(checks), 1)
        self.assertFalse(checks[0]["passed"])

    def test_period_and_unit_mismatch_fail_even_when_number_matches(self) -> None:
        validator = DeterministicNumericValidator()
        checks = validator.validate({"fact_id": "F1", "fact": "公司2024年收入同比增长20%"}, [{"content": "公司2023年收入同比增长20个百分点"}])
        self.assertFalse(checks[0]["passed"])

    def test_missing_page_is_allowed_but_missing_locator_is_not(self) -> None:
        evidence = {"evidence_id": "E1", "content": "事实", "document_id": "D1", "document_version": "v1", "content_hash": content_hash("事实")}
        self.assertTrue(citation_is_traceable(evidence))
        self.assertFalse(citation_is_traceable({"content": "事实", "page": 2}))

    def test_sufficiency_and_conflict_are_separate_concepts(self) -> None:
        assessments = [{"relation": "SUPPORTS", "usable": True}, {"relation": "CONTRADICTS", "usable": True}]
        self.assertEqual(evidence_status_from_relations(assessments), "SUFFICIENT")
        self.assertTrue(has_conflict(assessments))


class PolicyAndRetrievalTests(unittest.TestCase):
    def test_scope_is_applied_before_results_are_returned(self) -> None:
        candidates = [{"evidence_id": "allowed", "content": "收入增长", "document_id": "D1"}, {"evidence_id": "forbidden", "content": "收入增长", "document_id": "D2"}, {"evidence_id": "missing-metadata", "content": "收入增长"}]
        scope = {"allowed_document_ids": ["D1"], "company_ids": [], "periods": []}
        self.assertEqual([x["evidence_id"] for x in filter_by_scope(candidates, scope)], ["allowed"])
        retriever = ScopedInMemoryRetriever(candidates)
        self.assertEqual([x["evidence_id"] for x in retriever.retrieve({"query_text": "收入增长"}, scope)], ["allowed"])

    def test_rule_engine_is_versioned_and_only_returns_triggered_rules(self) -> None:
        engine = RuleEngine([Rule("r1", "v1", "reasoning_gap", "high", lambda c: c.get("bad", False), "bad")])
        self.assertEqual(engine.evaluate({"bad": False}), [])
        self.assertEqual(engine.evaluate({"bad": True})[0]["rule_id"], "r1")

    def test_risk_policy_escalates_counter_evidence_and_critical_child(self) -> None:
        policy = RiskPolicy()
        self.assertEqual(policy.decide(child={"importance": "high"}, initial_verdict={"confidence": "medium"}, rule_hits=[], has_counter_evidence=True)["next_step"], "critic")
        self.assertEqual(policy.decide(child={"importance": "critical"}, initial_verdict={"confidence": "high"}, rule_hits=[], has_counter_evidence=False)["next_step"], "human")
        self.assertEqual(confidence_band(status="SUPPORTED", evidence_count=2), "high")


if __name__ == "__main__":
    unittest.main()
