"""Structured Planning Agent for financial claims.

The class is intentionally provider-free.  It models the contract that an
LLM-backed planner must satisfy: expand a business concept into evidence
requirements and emit executable retrieval parameters.  A production adapter
can replace the heuristics while keeping the same ``plan``/``rewrite`` API.
"""

from __future__ import annotations

import re
from typing import Any


KNOWN_METRIC_IDS = {
    "current_assets", "current_liabilities", "quick_assets", "inventory", "prepayments",
    "total_liabilities", "total_assets", "ebit", "interest_expense", "current_ratio",
    "quick_ratio", "debt_to_assets", "interest_coverage", "liquidity_coverage_ratio",
    "net_stable_funding_ratio", "capital_adequacy_ratio", "cet1_ratio", "solvency_adequacy_ratio",
    "gross_margin", "net_profit", "revenue", "roe", "roa", "cash_ratio", "cash",
    "operating_cash_flow", "interest_bearing_debt", "revenue_growth", "profit_growth",
    "asset_growth", "asset_turnover", "inventory_turnover", "receivables_turnover",
    "accounts_receivable", "debt_to_equity", "revenue_volatility", "customer_concentration",
    "segment_revenue", "market_share", "rd_intensity", "audit_opinion", "internal_control",
    "related_party_transactions", "litigation", "regulatory_penalty",
}

KNOWN_FORMULA_IDS = KNOWN_METRIC_IDS | {
    "quick_ratio", "gross_margin", "net_margin", "roe", "roa", "revenue_growth",
    "profit_growth", "asset_growth", "cashflow_to_profit", "cashflow_to_debt",
    "asset_turnover", "inventory_turnover", "receivables_turnover", "debt_to_assets",
    "debt_to_equity", "interest_coverage", "current_ratio", "cash_ratio",
}
ALLOWED_RETRIEVAL_PROFILES = {"atomic_text", "financial_table", "structured_data", "hybrid", "table_lookup", "structured"}


def validate_retrieval_plan(plan: dict[str, Any], *, max_top_k: int = 200) -> dict[str, Any]:
    """Validate model output before a worker can execute it.

    This is an execution guardrail, not the semantic planner.  The LLM can
    choose the concept, needs and metrics, but cannot invent an index route,
    formula, or unbounded retrieval budget.
    """

    if not isinstance(plan, dict) or not isinstance(plan.get("requests"), list) or not plan["requests"]:
        raise ValueError("retrieval plan must contain non-empty requests")
    seen_needs: set[str] = set()
    for request in plan["requests"]:
        if not isinstance(request, dict) or not str(request.get("query_text", "")).strip():
            raise ValueError("retrieval request query_text is required")
        need_id = str(request.get("need_id", ""))
        if not need_id or need_id in seen_needs:
            raise ValueError("retrieval request need_id must be unique")
        seen_needs.add(need_id)
        profile = request.get("retrieval_profile") or "atomic_text"
        if profile not in ALLOWED_RETRIEVAL_PROFILES:
            raise ValueError(f"unknown retrieval_profile: {profile}")
        metric_ids = request.get("metric_ids") or []
        if not isinstance(metric_ids, list) or not set(map(str, metric_ids)) <= KNOWN_METRIC_IDS:
            raise ValueError("unknown metric_id in retrieval plan")
        formula_id = request.get("formula_id")
        if formula_id is not None and str(formula_id) not in KNOWN_FORMULA_IDS:
            raise ValueError("unknown formula_id in retrieval plan")
        for key in ("dense_top_k", "lexical_top_k", "rerank_top_n"):
            if key in request:
                value = request[key]
                if not isinstance(value, int) or not 0 < value <= max_top_k:
                    raise ValueError(f"invalid {key} in retrieval plan")
    return plan


class FinancialPlanningAgent:
    """Single planner for concept expansion and bounded query rewrites."""

    _PERIOD = re.compile(r"20\d{2}")

    def __init__(self, *, max_requests: int = 6) -> None:
        self.max_requests = max_requests

    def plan(
        self,
        child: dict[str, Any],
        parent: dict[str, Any],
        company: dict[str, Any] | None,
        attempt: int,
    ) -> list[dict[str, Any]]:
        return self.build_plan(child, parent, company, attempt=attempt)["requests"]

    def rewrite(
        self,
        child: dict[str, Any],
        parent: dict[str, Any],
        previous_queries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Rewrite only the unresolved query; preserve the old MVP contract."""

        company = previous_queries[0].get("company") if previous_queries else None
        attempt = len(previous_queries)
        return self.build_plan(child, parent, company, attempt=attempt)["requests"]

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
        fact = str(child.get("fact", "")).strip()
        if not fact:
            raise ValueError("child.fact must be a non-empty string")

        profile = entity_profile or self._entity_profile(company)
        concept = self._concept(fact)
        periods = self._periods(fact, parent.get("parent_text", ""))
        if not periods:
            periods = ["latest"]
        company_name = str((company or {}).get("company_name", "公司"))
        missing = set(missing_needs or [])

        if concept == "solvency":
            requests = self._solvency_requests(
                child, company_name, profile, periods, attempt, missing
            )
        else:
            requests = self._concept_requests(
                concept, child, parent, company, company_name, profile, periods, attempt, missing
            )

        requests = requests[: self.max_requests]
        plan = {
            "plan_id": f"RP-{child.get('fact_id', 'UNKNOWN')}-{attempt}",
            "claim_id": child.get("fact_id"),
            "analysis_concept": concept,
            "entity_profile": profile,
            "requests": requests,
            "stop_conditions": [
                "ALL_REQUIRED_NEEDS_COVERED",
                "NO_NEW_EVIDENCE",
                "BUDGET_EXHAUSTED",
            ],
            "attempt": attempt,
        }
        return validate_retrieval_plan(plan)

    @staticmethod
    def _entity_profile(company: dict[str, Any] | None) -> str:
        if not company:
            return "general_corporate"
        entity_type = str(company.get("entity_type", "")).lower()
        if entity_type in {"bank", "银行"}:
            return "bank"
        if entity_type in {"insurer", "insurance", "保险"}:
            return "insurer"
        if entity_type in {"real_estate", "房地产"}:
            return "real_estate"
        return str(company.get("entity_profile", "general_corporate"))

    @staticmethod
    def _concept(fact: str) -> str:
        # An explicitly quantified statement is a single factual claim.  Do
        # not expand it into the broader qualitative concept (for example,
        # “收入同比增长20%” should verify that number directly).
        if re.search(r"(?:为|是|同比|环比|增长|下降|上升|减少)\s*-?\d+(?:\.\d+)?\s*(?:%|个百分点|亿元|万元)?", fact):
            return "claim_fact"
        if any(term in fact for term in ("偿债能力", "偿债", "流动比率", "速动比率", "资产负债率")):
            return "solvency"
        if any(term in fact for term in ("盈利能力", "毛利率", "净利率", "净利润")):
            return "profitability"
        if any(term in fact for term in ("流动性", "短期偿债", "现金比率")):
            return "liquidity"
        if any(term in fact for term in ("现金流质量", "经营现金流")):
            return "cash_flow_quality"
        if any(term in fact for term in ("成长性", "增长能力", "增长", "增速")):
            return "growth"
        if any(term in fact for term in ("营运能力", "运营效率", "周转率", "周转天数")):
            return "operating_efficiency"
        if any(term in fact for term in ("杠杆", "负债风险", "债务风险", "财务风险")):
            return "leverage"
        if any(term in fact for term in ("经营稳定性", "业务稳定性", "收入稳定", "客户集中")):
            return "business_stability"
        if any(term in fact for term in ("竞争力", "市场地位", "市场份额")):
            return "market_competitiveness"
        if any(term in fact for term in ("治理", "合规", "内控", "审计意见", "诉讼", "处罚")):
            return "governance_compliance"
        return "claim_fact"

    @classmethod
    def _periods(cls, fact: str, parent: str) -> list[str]:
        values: list[str] = []
        for value in cls._PERIOD.findall(f"{fact} {parent}"):
            if value not in values:
                values.append(value)
        return values[:3]

    def _solvency_requests(
        self,
        child: dict[str, Any],
        company_name: str,
        profile: str,
        periods: list[str],
        attempt: int,
        missing: set[str],
    ) -> list[dict[str, Any]]:
        fact_id = str(child.get("fact_id", "UNKNOWN"))
        if profile == "bank":
            specs = [
                ("liquidity-regulatory", "流动性覆盖率 净稳定资金比例", ["liquidity_coverage_ratio", "net_stable_funding_ratio"], "table"),
                ("capital-regulatory", "资本充足率 核心一级资本充足率", ["capital_adequacy_ratio", "cet1_ratio"], "table"),
            ]
        elif profile == "insurer":
            specs = [
                ("solvency-regulatory", "偿付能力充足率", ["solvency_adequacy_ratio"], "table"),
                ("liquidity-explanation", "流动性风险 负债到期 现金流", [], "text"),
            ]
        else:
            specs = [
                ("current-ratio", "流动资产合计 流动负债合计", ["current_assets", "current_liabilities"], "table"),
                ("quick-ratio", "速动资产 存货 预付款项 流动负债合计", ["quick_assets", "inventory", "prepayments", "current_liabilities"], "table"),
                ("debt-to-assets", "负债合计 资产总计 资产负债率", ["total_liabilities", "total_assets"], "table"),
                ("interest-coverage", "息税前利润 利息费用 利息保障倍数", ["ebit", "interest_expense"], "table"),
                ("solvency-explanation", "偿债能力 流动性 债务到期压力 原因", [], "text"),
            ]

        requests: list[dict[str, Any]] = []
        for need_suffix, terms, metric_ids, evidence_type in specs:
            need_id = f"N-{need_suffix}"
            if missing and need_id not in missing and attempt > 0:
                continue
            query_id = f"Q-{fact_id}-{need_suffix}-{attempt}"
            formula_id = {
                "current-ratio": "current_ratio",
                "quick-ratio": "quick_ratio",
                "debt-to-assets": "debt_to_assets",
                "interest-coverage": "interest_coverage",
            }.get(need_suffix)
            requests.append(
                {
                    "query_id": query_id,
                    "fact_id": fact_id,
                    "need_id": need_id,
                    "query_text": f"{company_name} {' '.join(periods)} {terms}",
                    "retrieval_type": "table" if evidence_type == "table" else "text",
                    "retrieval_profile": "financial_table" if evidence_type == "table" else "atomic_text",
                    "evidence_type": evidence_type,
                    "evidence_types": [evidence_type, "structured"] if evidence_type == "table" else ["text"],
                    "metric_ids": metric_ids,
                    "formula_id": formula_id,
                    "periods": periods,
                    "statement_scope": "consolidated",
                    "attempt": attempt,
                    "company": {"company_name": company_name, "entity_profile": profile},
                    "dense_top_k": 40 if evidence_type == "text" else 20,
                    "lexical_top_k": 40 if evidence_type == "text" else 30,
                    "rerank_top_n": 10 if evidence_type == "text" else 8,
                }
            )
        return requests

    def _concept_requests(
        self,
        concept: str,
        child: dict[str, Any],
        parent: dict[str, Any],
        company: dict[str, Any] | None,
        company_name: str,
        profile: str,
        periods: list[str],
        attempt: int,
        missing: set[str],
    ) -> list[dict[str, Any]]:
        """Expand any qualitative finance concept into bounded evidence needs."""

        specs: dict[str, list[tuple[str, str, list[str], str, str | None]]] = {
            "profitability": [
                ("gross-margin", "毛利率", ["gross_margin"], "table", "gross_margin"),
                ("net-margin", "净利率 净利润 营业收入", ["net_profit", "revenue"], "table", "net_margin"),
                ("roe", "净资产收益率 ROE", ["roe"], "table", "roe"),
                ("roa", "总资产报酬率 ROA", ["roa"], "table", "roa"),
                ("profitability-explanation", "盈利能力 毛利率变化 成本费用 原因", [], "text", None),
            ],
            "liquidity": [
                ("current-ratio", "流动比率 流动资产 流动负债", ["current_ratio", "current_assets", "current_liabilities"], "table", "current_ratio"),
                ("quick-ratio", "速动比率 速动资产 流动负债", ["quick_ratio", "quick_assets", "current_liabilities"], "table", "quick_ratio"),
                ("cash-ratio", "现金比率 货币资金 流动负债", ["cash_ratio", "cash", "current_liabilities"], "table", "cash_ratio"),
                ("liquidity-explanation", "流动性风险 现金缺口 债务到期", [], "text", None),
            ],
            "growth": [
                ("revenue-growth", "营业收入 收入 同比增长 增速", ["revenue", "revenue_growth"], "table", "revenue_growth"),
                ("profit-growth", "净利润 利润 同比增长 增速", ["net_profit", "profit_growth"], "table", "profit_growth"),
                ("asset-growth", "资产总计 总资产 同比增长", ["total_assets", "asset_growth"], "table", "asset_growth"),
                ("growth-explanation", "增长驱动 业务量 价格 产品 市场 原因", [], "text", None),
            ],
            "cash_flow_quality": [
                ("operating-cash-flow", "经营活动现金流净额", ["operating_cash_flow"], "table", "operating_cash_flow"),
                ("cashflow-profit", "经营现金流 净利润 现金含量", ["operating_cash_flow", "net_profit"], "table", "cashflow_to_profit"),
                ("cashflow-debt", "经营现金流 有息负债 偿债覆盖", ["operating_cash_flow", "interest_bearing_debt"], "table", "cashflow_to_debt"),
                ("cashflow-explanation", "经营现金流 现金流质量 回款 应收账款 原因", [], "text", None),
            ],
            "operating_efficiency": [
                ("asset-turnover", "总资产周转率 营业收入 总资产", ["asset_turnover", "revenue", "total_assets"], "table", "asset_turnover"),
                ("inventory-turnover", "存货周转率 存货周转天数", ["inventory_turnover", "inventory"], "table", "inventory_turnover"),
                ("receivable-turnover", "应收账款周转率 应收账款周转天数", ["receivables_turnover", "accounts_receivable"], "table", "receivables_turnover"),
                ("efficiency-explanation", "营运能力 运营效率 周转 原因", [], "text", None),
            ],
            "leverage": [
                ("debt-to-assets", "资产负债率 负债合计 资产总计", ["debt_to_assets", "total_liabilities", "total_assets"], "table", "debt_to_assets"),
                ("debt-to-equity", "产权比率 负债权益比", ["debt_to_equity"], "table", "debt_to_equity"),
                ("interest-coverage", "利息保障倍数 息税前利润 利息费用", ["interest_coverage", "ebit", "interest_expense"], "table", "interest_coverage"),
                ("leverage-explanation", "债务风险 杠杆 债务到期 再融资 原因", [], "text", None),
            ],
            "business_stability": [
                ("revenue-volatility", "收入波动 营业收入 历年", ["revenue", "revenue_volatility"], "table", "revenue_volatility"),
                ("customer-concentration", "客户集中度 前五大客户", ["customer_concentration"], "table", "customer_concentration"),
                ("segment-stability", "主营业务 分部收入 业务结构", ["segment_revenue"], "table", None),
                ("stability-explanation", "经营稳定性 订单 需求 波动 原因", [], "text", None),
            ],
            "market_competitiveness": [
                ("market-share", "市场份额 行业地位", ["market_share"], "table", "market_share"),
                ("competitive-growth", "营业收入增长 市场增长 同比", ["revenue_growth"], "table", "revenue_growth"),
                ("rd-intensity", "研发投入 研发费用率", ["rd_intensity"], "table", "rd_intensity"),
                ("competition-explanation", "竞争力 护城河 客户 产品 竞争优势", [], "text", None),
            ],
            "governance_compliance": [
                ("audit-opinion", "审计意见 保留意见 否定意见", ["audit_opinion"], "text", None),
                ("internal-control", "内部控制 内控缺陷", ["internal_control"], "text", None),
                ("related-party", "关联交易 关联方", ["related_party_transactions"], "text", None),
                ("litigation-penalty", "重大诉讼 行政处罚 监管处罚", ["litigation", "regulatory_penalty"], "text", None),
                ("governance-explanation", "公司治理 合规风险 重大事项", [], "text", None),
            ],
        }
        selected = specs.get(concept)
        if not selected:
            return [self._generic_request(child, parent, company, attempt)]
        requests: list[dict[str, Any]] = []
        for suffix, terms, metric_ids, evidence_type, formula_id in selected:
            need_id = f"N-{suffix}"
            if missing and attempt > 0 and need_id not in missing:
                continue
            requests.append(self._make_request(
                child=child,
                company=company,
                company_name=company_name,
                profile=profile,
                periods=periods,
                attempt=attempt,
                need_id=need_id,
                query_suffix=suffix,
                terms=terms,
                metric_ids=metric_ids,
                evidence_type=evidence_type,
                formula_id=formula_id,
            ))
        return requests

    @staticmethod
    def _make_request(
        *,
        child: dict[str, Any],
        company: dict[str, Any] | None,
        company_name: str,
        profile: str,
        periods: list[str],
        attempt: int,
        need_id: str,
        query_suffix: str,
        terms: str,
        metric_ids: list[str],
        evidence_type: str,
        formula_id: str | None,
    ) -> dict[str, Any]:
        fact_id = str(child.get("fact_id", "UNKNOWN"))
        is_table = evidence_type == "table"
        return {
            "query_id": f"Q-{fact_id}-{query_suffix}-{attempt}",
            "fact_id": fact_id,
            "need_id": need_id,
            "query_text": f"{company_name} {' '.join(periods)} {terms}".strip(),
            "retrieval_type": "table" if is_table else "text",
            "retrieval_profile": "financial_table" if is_table else "atomic_text",
            "evidence_type": evidence_type,
            "evidence_types": [evidence_type, "structured"] if is_table else ["text"],
            "metric_ids": metric_ids,
            "formula_id": formula_id,
            "periods": periods,
            "statement_scope": "consolidated",
            "attempt": attempt,
            "company": {"company_name": company_name, "entity_profile": profile, **(company or {})},
            "dense_top_k": 40 if not is_table else 20,
            "lexical_top_k": 40 if not is_table else 30,
            "rerank_top_n": 10 if not is_table else 8,
        }

    @staticmethod
    def _generic_request(
        child: dict[str, Any],
        parent: dict[str, Any],
        company: dict[str, Any] | None,
        attempt: int,
    ) -> dict[str, Any]:
        fact = str(child["fact"])
        query = fact if attempt == 0 else f"{fact}；原始语境：{parent['parent_text']}"
        evidence_type = "table" if re.search(r"收入|利润|毛利率|净利率|资产负债率|流动比率|速动比率|比例|比率|周转率|金额|数值|现金流|净资产收益率|ROE|ROA", fact, re.I) else "text"
        return {
            "query_id": f"Q-{child['fact_id']}-{attempt}",
            "fact_id": child["fact_id"],
            "need_id": f"N-{child['fact_id']}",
            "query_text": query,
            "retrieval_type": evidence_type,
            "retrieval_profile": "financial_table" if evidence_type == "table" else "atomic_text",
            "evidence_type": evidence_type,
            "evidence_types": [evidence_type],
            "attempt": attempt,
            "company": company,
            "dense_top_k": 40,
            "lexical_top_k": 40,
            "rerank_top_n": 10,
        }
