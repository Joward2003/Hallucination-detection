from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from credit_review.domain.models import Evidence
from credit_review.graph.builder import MvpServices, build_review_graph, default_services, run_review, resume_review
from credit_review.services.mvp_services import DeterministicParentChildExtractor


class ParentChildExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = DeterministicParentChildExtractor()

    def test_joint_driver_is_not_split_into_two_individual_causes(self) -> None:
        text = "公司2024年营业收入同比增长20%，主要受海外市场拓展和新产品放量带动，但由于原材料成本上升，毛利率同比下降2个百分点。"
        groups = self.extractor.extract(text)
        self.assertEqual(len(groups), 1)
        parent = groups[0]["parent"]
        children = groups[0]["children"]
        self.assertEqual(parent["parent_text"], text)
        child_texts = [item["fact"] for item in children]
        self.assertIn("海外市场拓展和新产品放量共同构成公司营业收入增长的主要驱动因素", child_texts)
        self.assertNotIn("海外市场拓展推动收入增长", child_texts)
        self.assertTrue(all(item["parent_id"] == parent["parent_id"] for item in children))

    def test_combined_causes_do_not_each_receive_full_amount(self) -> None:
        text = "由于原材料价格上涨和运输成本增加，公司毛利率同比下降3个百分点。"
        children = self.extractor.extract(text)[0]["children"]
        child_texts = [item["fact"] for item in children]
        self.assertIn("公司毛利率同比下降3个百分点", child_texts)
        self.assertFalse(any("原材料价格上涨导致" in item for item in child_texts))
        self.assertFalse(any("运输成本增加导致" in item for item in child_texts))

    def test_uncertainty_is_not_strengthened(self) -> None:
        text = "管理层预计，随着海外需求回暖，公司2025年收入可能实现进一步增长。"
        children = self.extractor.extract(text)[0]["children"]
        self.assertEqual(len(children), 1)
        self.assertIn("预计", children[0]["fact"])
        self.assertIn("可能", children[0]["fact"])

    def test_generated_children_remain_inside_parent_span(self) -> None:
        text = "公司2024年营业收入同比增长20%，主要受海外市场拓展和新产品放量带动。"
        group = self.extractor.extract(text)[0]
        parent = group["parent"]
        self.assertTrue(all(parent["source_start"] <= child["source_start"] <= child["source_end"] <= parent["source_end"] for child in group["children"]))


class ReviewGraphTests(unittest.TestCase):
    def test_agent_loop_trace_reports_plan_retrieval_and_risk_routes(self) -> None:
        events = []
        state = run_review(
            "公司偿债能力较强。",
            evidence=[
                {"evidence_id": "E-current", "content": "公司2024年流动资产合计120亿元，流动负债合计80亿元。", "source": "annual", "page": 10, "evidence_type": "table"},
                {"evidence_id": "E-quick", "content": "公司2024年速动资产90亿元，流动负债80亿元。", "source": "annual", "page": 10, "evidence_type": "table"},
            ],
            trace=events.append,
        )

        completed_nodes = [event["node"] for event in events if event["type"] == "node_finish"]
        self.assertIn("extract_parent_child", completed_nodes)
        self.assertIn("plan_query", completed_nodes)
        self.assertIn("retrieve", completed_nodes)
        self.assertIn("grade_evidence", completed_nodes)
        self.assertIn("risk_gate", completed_nodes)
        plan_event = next(event for event in events if event["type"] == "node_finish" and event["node"] == "plan_query")
        request_params = plan_event["summary"]["requests"]
        self.assertTrue(any(request.get("formula_id") == "current_ratio" for request in request_params))
        self.assertTrue(all("dense_top_k" in request and "lexical_top_k" in request for request in request_params))
        retrieval_event = next(event for event in events if event["type"] == "node_finish" and event["node"] == "retrieve")
        self.assertTrue(retrieval_event["summary"]["queries"])
        self.assertTrue(any(
            candidate.get("route_hits")
            for query in retrieval_event["summary"]["queries"]
            for candidate in query.get("candidates", [])
        ))
        self.assertTrue(any(event["type"] == "route" and event["source"] == "grade_evidence" for event in events))
        self.assertEqual(state["workflow_status"], "COMPLETED")

    def test_empty_report_and_invalid_evidence_are_rejected_at_boundary(self) -> None:
        with self.assertRaises(ValueError):
            run_review("  ")
        with self.assertRaises(ValueError):
            run_review("事实。", evidence=[{"evidence_id": "E", "content": 3, "source": "s"}])

    def test_supported_result_contains_parent_child_and_external_evidence(self) -> None:
        evidence = [
            Evidence(
                evidence_id="E01",
                content="公司2024年营业收入同比增长20%",
                source="annual_report_2024",
                page=32,
                evidence_type="table",
                score=0.0,
            )
        ]
        state = run_review("公司2024年营业收入同比增长20%。", evidence=evidence)
        result = state["review_result"]
        child_result = result["completed_results"][0]
        self.assertEqual(child_result["status"], "SUPPORTED")
        self.assertEqual(child_result["parent_id"], "P001")
        self.assertEqual(child_result["parent_text"], "公司2024年营业收入同比增长20%。")
        self.assertEqual(child_result["evidence"][0]["evidence_id"], "E01")

    def test_empty_evidence_is_insufficient_after_one_rewrite(self) -> None:
        state = run_review("公司2024年营业收入同比增长20%。")
        child_result = state["review_result"]["completed_results"][0]
        self.assertEqual(child_result["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(child_result["retry_count"], 1)
        self.assertEqual(state["current_evidence"], [])
        self.assertEqual(state["current_fact"], {})

    def test_opposite_direction_is_contradicted(self) -> None:
        evidence = [
            Evidence(
                evidence_id="E02",
                content="公司2024年营业收入同比下降5%",
                source="annual_report_2024",
                page=32,
                evidence_type="table",
                score=0.0,
            )
        ]
        state = run_review("公司2024年营业收入同比增长20%。", evidence=evidence)
        result = state["review_result"]["completed_results"][0]
        self.assertEqual(result["status"], "CONTRADICTED")
        self.assertEqual(result["counter_evidence_ids"], ["E02"])

    def test_supporting_evidence_with_unrelated_amount_does_not_become_counter_evidence(self) -> None:
        state = run_review(
            "公司（600001）2024年营业收入同比增长20%。",
            evidence=[Evidence("E07", "公司2024年营业收入为120亿元，同比增长20%", "annual_report", 10, "table", 0.0)],
        )
        result = state["review_result"]["completed_results"][0]
        self.assertEqual(result["status"], "SUPPORTED")
        self.assertEqual(result["counter_evidence_ids"], [])

    def test_json_evidence_is_normalized_at_public_boundary(self) -> None:
        state = run_review(
            "公司2024年营业收入同比增长20%。",
            evidence=[
                {
                    "evidence_id": "E03",
                    "content": "公司2024年营业收入同比增长20%",
                    "source": "annual_report_2024",
                    "page": 32,
                    "evidence_type": "table",
                }
            ],
        )
        self.assertEqual(state["review_result"]["completed_results"][0]["status"], "SUPPORTED")

    def test_source_scope_filters_evidence_before_verification(self) -> None:
        state = run_review(
            "公司2024年营业收入同比增长20%。",
            evidence=[
                {"evidence_id": "allowed", "content": "公司2024年营业收入同比增长20%", "source": "annual", "document_id": "D1"},
                {"evidence_id": "outside", "content": "公司2024年营业收入同比增长20%", "source": "annual", "document_id": "D2"},
            ],
            source_scope={"allowed_document_ids": ["D1"], "company_ids": [], "periods": []},
        )
        evidence_ids = [item["evidence_id"] for item in state["review_result"]["completed_results"][0]["evidence"]]
        self.assertEqual(evidence_ids, ["allowed"])

    def test_children_are_processed_sequentially_and_current_state_is_cleared(self) -> None:
        state = run_review(
            "公司2024年营业收入同比增长20%。公司2025年利润同比下降5%。",
            evidence=[
                Evidence("E04", "公司2024年营业收入同比增长20%", "annual_report", 10, "table", 0.0),
                Evidence("E05", "公司2025年利润同比下降5%", "annual_report", 11, "table", 0.0),
            ],
        )
        results = state["review_result"]["completed_results"]
        self.assertEqual([item["parent_id"] for item in results], ["P001", "P002"])
        self.assertEqual([item["status"] for item in results], ["SUPPORTED", "SUPPORTED"])
        self.assertEqual(state["child_index"], 2)
        self.assertEqual(state["current_parent"], {})
        self.assertEqual(state["current_fact"], {})
        self.assertEqual(state["current_queries"], [])
        self.assertEqual(state["current_evidence"], [])

    def test_extended_child_path_runs_numeric_rules_and_critic(self) -> None:
        supported = run_review(
            "公司2024年营业收入同比增长20%。",
            evidence=[Evidence("E06", "公司2024年营业收入同比增长20%", "annual_report", 10, "table", 0.0)],
        )
        child = supported["review_result"]["completed_results"][0]
        self.assertTrue(child["numeric_checks"])
        self.assertEqual(child["numeric_checks"][0]["passed"], True)
        self.assertEqual(child["critic_verdict"], None)

        insufficient = run_review("公司2024年营业收入同比增长20%。")
        child = insufficient["review_result"]["completed_results"][0]
        self.assertEqual(child["status"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNotNone(child["critic_verdict"])

    def test_planning_agent_plan_is_carried_into_child_result(self) -> None:
        state = run_review(
            "公司偿债能力较强。",
            companies={"公司": {"entity_type": "general_corporate"}},
            evidence=[
                {"evidence_id": "E-current", "content": "公司2024年流动资产合计120亿元，流动负债合计80亿元。", "source": "annual", "page": 10, "evidence_type": "table"},
                {"evidence_id": "E-quick", "content": "公司2024年速动资产90亿元，流动负债80亿元。", "source": "annual", "page": 10, "evidence_type": "table"},
            ],
        )
        child = state["review_result"]["completed_results"][0]
        plan = child["retrieval_plan"]
        self.assertEqual(plan["analysis_concept"], "solvency")
        self.assertGreaterEqual(len(plan["requests"]), 4)
        self.assertTrue(any(item.get("formula_id") == "current_ratio" for item in plan["requests"]))
        self.assertTrue(all("dense_top_k" in item and "lexical_top_k" in item for item in plan["requests"]))

    def test_retrieval_trace_and_evidence_observation_are_persisted(self) -> None:
        state = run_review(
            "公司盈利能力较强。",
            evidence=[{"evidence_id": "E-margin", "content": "公司2024年毛利率为35%。", "source": "annual", "page": 12, "evidence_type": "table"}],
        )
        child = state["review_result"]["completed_results"][0]
        self.assertTrue(child["evidence_requirements"])
        self.assertTrue(child["retrieval_trace"])
        self.assertIn("covered_needs", child["evidence_observation"])
        self.assertIn("missing_needs", child["evidence_observation"])
        self.assertTrue(any(item["need_id"] == "N-gross-margin" for item in child["retrieval_trace"]))

    def test_critical_child_pauses_for_human_review_and_can_resume(self) -> None:
        base = default_services()

        class CriticalExtractor:
            def extract(self, _text):
                return [{"parent": {"parent_id": "P001", "parent_text": "关键事实", "source_start": 0, "source_end": 4}, "children": [{"fact_id": "F00101", "parent_id": "P001", "fact": "关键事实", "source_start": 0, "source_end": 4, "importance": "critical"}]}]

        services = MvpServices(CriticalExtractor(), base.company_resolver, base.query_planner, base.retriever, base.grader, base.verifier, numeric_validator=base.numeric_validator, rule_engine=base.rule_engine, risk_policy=base.risk_policy, critic_verifier=base.critic_verifier)
        paused = build_review_graph(services).invoke({"original_input": "关键事实"})
        self.assertEqual(paused["workflow_status"], "HUMAN_REVIEW_REQUIRED")
        self.assertEqual(paused["human_task"]["status"], "PENDING")
        completed = resume_review(paused, {"task_version": 1, "decision": "SUPPORTED", "comment": "人工确认", "decided_by": "reviewer"})
        self.assertEqual(completed["workflow_status"], "COMPLETED")
        self.assertEqual(completed["review_result"]["completed_results"][0]["status"], "SUPPORTED")


if __name__ == "__main__":
    unittest.main()
