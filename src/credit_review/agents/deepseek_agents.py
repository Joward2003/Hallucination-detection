"""DeepSeek-backed optional agents with deterministic safety fallbacks."""

from __future__ import annotations

from typing import Any

from credit_review.domain.invariants import validate_fact_groups, validate_verdict
from credit_review.agents.planning_agent import FinancialPlanningAgent, validate_retrieval_plan
from credit_review.services.mvp_services import (
    DeterministicParentChildExtractor,
    MvpFactVerifier,
)


class DeepSeekParentChildExtractor:
    def __init__(self, gateway: Any, fallback: Any | None = None) -> None:
        self.gateway = gateway
        self.fallback = fallback or DeterministicParentChildExtractor()

    def extract(self, original_input: str) -> list[dict[str, Any]]:
        messages = [
            {"role": "system", "content": "你是金融报告事实抽取器。只返回 JSON，不输出解释或思维过程。必须保留原始 Parent 语境；联合因果不得拆成单因素因果；保留主体、期间、数字、单位和不确定性。"},
            {"role": "user", "content": f"请抽取以下报告的 Parent–Child 结构，并为 Parent/Child 提供 source_start/source_end。输出 {{\"fact_groups\":[...]}}。\n报告：{original_input}"},
        ]
        try:
            data = self.gateway.complete_json(messages)
            groups = data.get("fact_groups")
            if not isinstance(groups, list):
                raise ValueError("fact_groups missing")
            validate_fact_groups(groups)
            return groups
        except Exception:
            return self.fallback.extract(original_input)


class DeepSeekQueryPlanner:
    def __init__(self, gateway: Any, fallback: Any | None = None) -> None:
        self.gateway = gateway
        self.fallback = fallback or FinancialPlanningAgent()

    def build_plan(
        self,
        child: dict[str, Any],
        parent: dict[str, Any],
        company: dict[str, Any] | None,
        *,
        attempt: int = 0,
        missing_needs: list[str] | None = None,
        entity_profile: str | None = None,
    ) -> dict[str, Any]:
        """Ask the model for the complete plan, then validate its executable shape.

        The model is responsible for semantic concept expansion.  The local
        fallback supplies metadata only when the provider is unavailable or
        returns the legacy ``{"queries": [...]}`` shape.
        """

        fallback_plan = self._fallback_plan(
            child, parent, company, attempt=attempt,
            missing_needs=missing_needs, entity_profile=entity_profile,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "你是金融报告的 Planning Agent。由你判断定性 Claim 需要哪些可验证证据，"
                    "将业务概念展开为指标、公式、期间和原文解释需求。只返回 JSON，不返回最终结论或思维过程。"
                    "只能选择指标注册表中的 metric_id/formula_id；不能改变租户、知识库、权限和预算。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "为 Child 生成一个可检索查询和完整 RetrievalPlan。输出首选格式："
                    "{\"plan\":{\"analysis_concept\":\"...\",\"entity_profile\":\"...\","
                    "\"requests\":[{\"need_id\":\"...\",\"query_text\":\"...\","
                    "\"retrieval_profile\":\"financial_table|atomic_text|structured_data\","
                    "\"metric_ids\":[],\"formula_id\":null,\"periods\":[],"
                    "\"evidence_types\":[\"table|text|structured\"],"
                    "\"dense_top_k\":20,\"lexical_top_k\":30,\"rerank_top_n\":8}],"
                    "\"stop_conditions\":[\"...\"]}}。"
                    "若无法生成完整计划，仍可返回旧格式 {\"queries\":[...]}。"
                    f"Child：{child['fact']}；Parent：{parent['parent_text']}；公司：{company or {}}；"
                    f"第 {attempt} 次尝试；当前缺口：{missing_needs or []}。"
                ),
            },
        ]
        try:
            data = self.gateway.complete_json(messages)
            raw_plan = data.get("plan") if isinstance(data, dict) else None
            if not isinstance(raw_plan, dict):
                raw_plan = data if isinstance(data, dict) else {}
            raw_requests = raw_plan.get("requests") or raw_plan.get("queries")
            if not isinstance(raw_requests, list) or not raw_requests:
                raise ValueError("retrieval plan requests missing")
            requests = self._normalize_requests(raw_requests, child, company, attempt)
            plan = dict(fallback_plan)
            plan.update({key: raw_plan[key] for key in ("analysis_concept", "entity_profile", "stop_conditions") if key in raw_plan})
            plan["requests"] = requests[: self._max_requests()]
            plan["plan_id"] = str(raw_plan.get("plan_id") or plan["plan_id"])
            plan["attempt"] = attempt
            return validate_retrieval_plan(plan)
        except Exception as exc:
            if hasattr(self.gateway, "record"):
                self.gateway.record("planning_fallback", {"error_type": type(exc).__name__, "reason": str(exc), "fallback_plan": fallback_plan})
            return fallback_plan

    def plan(self, child: dict[str, Any], parent: dict[str, Any], company: dict[str, Any] | None, attempt: int) -> list[dict[str, Any]]:
        return self.build_plan(child, parent, company, attempt=attempt)["requests"]

    def rewrite(self, child: dict[str, Any], parent: dict[str, Any], previous_queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        missing = [str(item.get("need_id")) for item in previous_queries if item.get("need_id")]
        return self.build_plan(child, parent, None, attempt=len(previous_queries), missing_needs=missing or None)["requests"]

    def _fallback_plan(self, child: dict[str, Any], parent: dict[str, Any], company: dict[str, Any] | None, *, attempt: int, missing_needs: list[str] | None, entity_profile: str | None) -> dict[str, Any]:
        if hasattr(self.fallback, "build_plan"):
            return self.fallback.build_plan(child, parent, company, attempt=attempt, missing_needs=missing_needs, entity_profile=entity_profile)
        requests = self.fallback.plan(child, parent, company, attempt)
        return {"plan_id": f"RP-{child['fact_id']}-{attempt}", "claim_id": child["fact_id"], "analysis_concept": "claim_fact", "entity_profile": entity_profile or "general_corporate", "requests": requests, "stop_conditions": ["ALL_REQUIRED_NEEDS_COVERED", "NO_NEW_EVIDENCE", "BUDGET_EXHAUSTED"], "attempt": attempt}

    def _max_requests(self) -> int:
        return int(getattr(self.fallback, "max_requests", 6))

    @staticmethod
    def _normalize_requests(raw_requests: list[Any], child: dict[str, Any], company: dict[str, Any] | None, attempt: int) -> list[dict[str, Any]]:
        requests: list[dict[str, Any]] = []
        for index, item in enumerate(raw_requests, 1):
            if not isinstance(item, dict) or not isinstance(item.get("query_text"), str) or not item["query_text"].strip():
                raise ValueError("invalid query schema")
            retrieval_type = item.get("retrieval_type") or ("table" if item.get("retrieval_profile") == "financial_table" else "text")
            if retrieval_type not in {"text", "table"}:
                raise ValueError("invalid retrieval_type")
            profile = item.get("retrieval_profile") or ("financial_table" if retrieval_type == "table" else "atomic_text")
            if profile not in {"atomic_text", "financial_table", "structured_data", "hybrid", "table_lookup", "structured"}:
                raise ValueError("invalid retrieval_profile")
            normalized = dict(item)
            normalized.update({
                "query_id": str(item.get("query_id") or f"Q-{child['fact_id']}-{attempt}-{index}"),
                "fact_id": child["fact_id"],
                "need_id": str(item.get("need_id") or f"N-{child['fact_id']}-{index}"),
                "retrieval_type": retrieval_type,
                "retrieval_profile": profile,
                "attempt": attempt,
                "company": item.get("company") or company,
                "metric_ids": list(item.get("metric_ids") or []),
                "periods": list(item.get("periods") or []),
                "evidence_types": list(item.get("evidence_types") or ([retrieval_type] if retrieval_type else [])),
            })
            requests.append(normalized)
        return requests


class DeepSeekFactVerifier:
    def __init__(self, gateway: Any, fallback: Any | None = None) -> None:
        self.gateway = gateway
        self.fallback = fallback or MvpFactVerifier()

    def verify(self, child: dict[str, Any], parent: dict[str, Any], evidence: list[dict[str, Any]], assessments: list[dict[str, Any]], evidence_status: str) -> dict[str, Any]:
        messages = [{"role": "system", "content": "你是金融报告事实核验器。只返回 JSON，不输出思维过程。允许 status：SUPPORTED、CONTRADICTED、INSUFFICIENT_EVIDENCE；confidence_band：low、medium、high。Parent 只能作为语境，不能作为证据。"}, {"role": "user", "content": f"【待核验 Child Fact】{child['fact']}\n【原始语境 Parent】{parent['parent_text']}\n【外部 Evidence】{evidence}\n【Evidence Assessment】{assessments}\n当前证据状态：{evidence_status}\n输出 {{\"status\":\"...\",\"reason\":\"简短可审计理由\",\"evidence_ids\":[],\"confidence_band\":\"...\"}}"}]
        try:
            data = self.gateway.complete_json(messages)
            validate_verdict({"status": data.get("status"), "confidence_band": data.get("confidence_band")})
            evidence_ids = [str(item) for item in data.get("evidence_ids", [])]
            valid_ids = {str(item.get("evidence_id")) for item in evidence}
            if not set(evidence_ids) <= valid_ids:
                raise ValueError("verdict cited unknown evidence")
            return {"status": data["status"], "reason": str(data.get("reason", "模型返回的可审计理由。"))[:1000], "evidence_ids": evidence_ids, "confidence": data["confidence_band"], "counter_evidence_ids": [item for item in evidence_ids if any(a.get("evidence_id") == item and a.get("relation") == "CONTRADICTS" for a in assessments)]}
        except Exception:
            return self.fallback.verify(child, parent, evidence, assessments, evidence_status)
