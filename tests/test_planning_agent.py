from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from credit_review.agents.planning_agent import FinancialPlanningAgent, validate_retrieval_plan


class PlanningAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = FinancialPlanningAgent()
        self.child = {"fact_id": "F1", "fact": "公司偿债能力较强"}
        self.parent = {"parent_text": "公司2024年年报"}

    def test_concept_expands_to_structured_metric_requests(self) -> None:
        plan = self.agent.build_plan(
            self.child,
            self.parent,
            {"company_name": "甲公司"},
        )
        self.assertEqual(plan["analysis_concept"], "solvency")
        self.assertEqual(plan["entity_profile"], "general_corporate")
        self.assertGreaterEqual(len(plan["requests"]), 4)
        current = next(item for item in plan["requests"] if item["need_id"] == "N-current-ratio")
        self.assertEqual(current["formula_id"], "current_ratio")
        self.assertEqual(current["retrieval_profile"], "financial_table")
        self.assertIn("current_assets", current["metric_ids"])
        self.assertEqual(current["periods"], ["2024"])
        self.assertGreater(current["dense_top_k"], 0)

    def test_bank_profile_does_not_use_general_corporate_ratios(self) -> None:
        plan = self.agent.build_plan(
            self.child,
            self.parent,
            {"company_name": "甲银行", "entity_type": "bank"},
        )
        self.assertEqual(plan["entity_profile"], "bank")
        metric_ids = [metric for item in plan["requests"] for metric in item.get("metric_ids", [])]
        self.assertIn("capital_adequacy_ratio", metric_ids)
        self.assertNotIn("current_assets", metric_ids)

    def test_rewrite_can_target_only_missing_need(self) -> None:
        plan = self.agent.build_plan(
            self.child,
            self.parent,
            {"company_name": "甲公司"},
            attempt=1,
            missing_needs=["N-current-ratio"],
        )
        self.assertEqual([item["need_id"] for item in plan["requests"]], ["N-current-ratio"])

    def test_qualitative_concepts_all_expand_to_multiple_evidence_needs(self) -> None:
        examples = {
            "公司盈利能力较强": ("profitability", "gross_margin"),
            "公司成长性良好": ("growth", "revenue_growth"),
            "公司现金流质量较高": ("cash_flow_quality", "operating_cash_flow"),
            "公司营运能力较强": ("operating_efficiency", "asset_turnover"),
            "公司杠杆风险可控": ("leverage", "debt_to_assets"),
            "公司治理合规稳健": ("governance_compliance", "audit_opinion"),
        }
        for fact, (concept, expected_metric) in examples.items():
            with self.subTest(fact=fact):
                plan = self.agent.build_plan(
                    {"fact_id": "F2", "fact": fact},
                    {"parent_text": "公司2024年年报"},
                    {"company_name": "甲公司"},
                )
                self.assertEqual(plan["analysis_concept"], concept)
                self.assertGreaterEqual(len(plan["requests"]), 2)
                metric_ids = [metric for item in plan["requests"] for metric in item.get("metric_ids", [])]
                self.assertIn(expected_metric, metric_ids)
                self.assertTrue(all(item.get("query_text") and item.get("retrieval_profile") for item in plan["requests"]))

    def test_execution_guardrail_rejects_unknown_metric_and_unbounded_top_k(self) -> None:
        request = {
            "need_id": "N1",
            "query_text": "甲公司指标",
            "retrieval_profile": "financial_table",
            "metric_ids": ["model_invented_metric"],
            "dense_top_k": 1000,
        }
        with self.assertRaises(ValueError):
            validate_retrieval_plan({"requests": [request]})


if __name__ == "__main__":
    unittest.main()
