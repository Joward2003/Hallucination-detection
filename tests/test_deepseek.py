from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from credit_review.config.models import DeepSeekConfig
from credit_review.graph.builder import run_review_with_deepseek
from credit_review.infrastructure.deepseek_gateway import DeepSeekGateway


class FakeGatewayClient:
    def __init__(self) -> None:
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))])


class FailingGatewayClient(FakeGatewayClient):
    def create(self, **kwargs):
        self.calls.append(kwargs)
        raise RuntimeError("provider failure")


class PlanningGateway:
    def __init__(self) -> None:
        self.calls = []

    def complete_json(self, messages):
        self.calls.append(messages)
        prompt = messages[-1]["content"]
        if "Planning Agent" in messages[0]["content"]:
            return {
                "plan": {
                    "plan_id": "llm-plan-1",
                    "analysis_concept": "profitability",
                    "entity_profile": "general_corporate",
                    "requests": [
                        {
                            "need_id": "N-gross-margin",
                            "query_text": "甲公司 2024 毛利率",
                            "retrieval_profile": "financial_table",
                            "retrieval_type": "table",
                            "metric_ids": ["gross_margin"],
                            "formula_id": "gross_margin",
                            "periods": ["2024"],
                            "evidence_types": ["table", "structured"],
                            "dense_top_k": 12,
                            "lexical_top_k": 20,
                            "rerank_top_n": 5,
                        },
                        {
                            "need_id": "N-profitability-explanation",
                            "query_text": "甲公司 2024 盈利能力 成本费用原因",
                            "retrieval_profile": "atomic_text",
                            "retrieval_type": "text",
                            "metric_ids": [],
                            "periods": ["2024"],
                        },
                    ],
                    "stop_conditions": ["ALL_REQUIRED_NEEDS_COVERED"],
                }
            }
        if "抽取以下报告" in prompt:
            return {"fact_groups": []}
        return {"status": "SUPPORTED", "reason": "ok", "evidence_ids": [], "confidence_band": "medium"}


class FakeStructuredGateway:
    def __init__(self) -> None:
        self.calls = []

    def complete_json(self, messages):
        prompt = messages[-1]["content"]
        self.calls.append(messages)
        if "抽取以下报告" in prompt:
            return {"fact_groups": [{"parent": {"parent_id": "P001", "parent_text": "公司2024年营业收入同比增长20%。", "source_start": 0, "source_end": 20}, "children": [{"fact_id": "F00101", "parent_id": "P001", "fact": "公司2024年营业收入同比增长20%", "source_start": 0, "source_end": 19}]}]}
        if "生成一个可检索查询" in prompt:
            return {"queries": [{"query_text": "公司2024年营业收入同比增长20%", "retrieval_type": "table"}]}
        return {"status": "SUPPORTED", "reason": "外部证据与事实一致", "evidence_ids": ["E1"], "confidence_band": "medium"}


class DeepSeekConfigTests(unittest.TestCase):
    def test_configuration_reads_key_from_environment_and_safe_dict_hides_it(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret-test-key", "DEEPSEEK_MODEL": "custom-model"}, clear=True):
            config = DeepSeekConfig.from_env(require_key=True)
        self.assertEqual(config.model, "custom-model")
        self.assertEqual(config.api_key, "secret-test-key")
        self.assertNotIn("secret-test-key", repr(config))
        self.assertNotIn("secret-test-key", str(config.safe_dict()))
        self.assertFalse("api_key" in config.safe_dict())

    def test_missing_key_is_rejected_before_client_creation(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                DeepSeekConfig.from_env(require_key=True)

    def test_gateway_uses_openai_compatible_request_without_leaking_key(self) -> None:
        client = FakeGatewayClient()
        config = DeepSeekConfig(api_key="secret-test-key")
        gateway = DeepSeekGateway(config, client=client)
        self.assertEqual(gateway.complete_json([{"role": "user", "content": "ping"}]), {"ok": True})
        self.assertEqual(client.calls[0]["model"], "deepseek-v4-flash")
        self.assertEqual(client.calls[0]["response_format"], {"type": "json_object"})
        self.assertEqual(client.calls[0]["extra_body"], {"thinking": {"type": "disabled"}})

    def test_gateway_sanitizes_provider_errors(self) -> None:
        client = FailingGatewayClient()
        gateway = DeepSeekGateway(DeepSeekConfig(api_key="secret-test-key"), client=client)
        with self.assertRaisesRegex(RuntimeError, "DeepSeek API request failed") as raised:
            gateway.complete([{"role": "user", "content": "ping"}])
        self.assertNotIn("secret-test-key", str(raised.exception))

    def test_deepseek_agents_are_wired_to_existing_graph_and_deterministic_checks_remain(self) -> None:
        gateway = FakeStructuredGateway()
        trace = []
        state = run_review_with_deepseek(
            "公司2024年营业收入同比增长20%。",
            evidence=[{"evidence_id": "E1", "content": "公司2024年营业收入同比增长20%", "source": "annual", "page": 1, "evidence_type": "table"}],
            gateway=gateway,
            trace=trace.append,
        )
        child = state["review_result"]["completed_results"][0]
        self.assertEqual(child["status"], "SUPPORTED")
        self.assertTrue(child["numeric_checks"])
        self.assertGreaterEqual(len(gateway.calls), 3)
        traced_nodes = {event["node"] for event in trace if event["type"] == "node_finish"}
        self.assertTrue({"plan_query", "retrieve", "grade_evidence", "verify", "risk_gate"} <= traced_nodes)

    def test_planning_agent_accepts_llm_retrieval_plan_shape(self) -> None:
        from credit_review.agents.deepseek_agents import DeepSeekQueryPlanner

        gateway = PlanningGateway()
        planner = DeepSeekQueryPlanner(gateway)
        plan = planner.build_plan(
            {"fact_id": "F1", "fact": "公司盈利能力较强"},
            {"parent_text": "公司2024年年报"},
            {"company_name": "甲公司"},
        )
        self.assertEqual(plan["plan_id"], "llm-plan-1")
        self.assertEqual(plan["analysis_concept"], "profitability")
        self.assertEqual(plan["requests"][0]["metric_ids"], ["gross_margin"])
        self.assertEqual(plan["requests"][0]["retrieval_profile"], "financial_table")


if __name__ == "__main__":
    unittest.main()
