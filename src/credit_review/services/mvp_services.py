"""Provider-free services for the first executable review loop.

These implementations are intentionally conservative and replaceable. They
make the State/routing contract executable before introducing LLM or Chroma
failure modes.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from credit_review.domain.models import (
    ChildFact,
    Evidence,
    EvidenceAssessment,
    EvidenceStatus,
    FactGroup,
    ParentContext,
    VerificationResult,
)


def _split_parents(text: str) -> list[tuple[str, int, int]]:
    parts: list[tuple[str, int, int]] = []
    start = 0
    for match in re.finditer(r"[。！？!?]+", text):
        end = match.end()
        value = text[start:end].strip()
        if value:
            left = text.find(value, start, end)
            parts.append((value, left, left + len(value)))
        start = end
    tail = text[start:].strip()
    if tail:
        left = text.find(tail, start)
        parts.append((tail, left, left + len(tail)))
    return parts or [(text, 0, len(text))]


class DeterministicParentChildExtractor:
    """Conservative MVP extractor.

    It recognizes only a few unambiguous financial sentence patterns. Unknown
    patterns remain one Child equal to the Parent, preserving semantics rather
    than making an unsafe split.
    """

    def extract(self, original_input: str) -> list[dict[str, Any]]:
        if not isinstance(original_input, str) or not original_input.strip():
            raise ValueError("original_input must be a non-empty string")
        groups: list[dict[str, Any]] = []
        for index, (parent_text, start, end) in enumerate(_split_parents(original_input), 1):
            parent = ParentContext(f"P{index:03d}", parent_text, start, end)
            children = self._children_for(parent)
            groups.append({"parent": asdict(parent), "children": [asdict(c) for c in children]})
        return groups

    def _children_for(self, parent: ParentContext) -> list[ChildFact]:
        text = parent.parent_text
        children: list[str] = []

        # Explicitly preserve joint causality: A and B jointly drive C.
        driver = re.search(r"主要受(.+?)(?:带动|推动)", text)
        if driver and ("营业收入" in text or "收入" in text):
            base = re.split(r"[，,]主要受", text, maxsplit=1)[0].strip()
            if base:
                children.append(base)
            drivers = driver.group(1).strip()
            children.append(f"{drivers}共同构成公司营业收入增长的主要驱动因素")

            margin = re.search(r"由于(.+?)，([^，。]+毛利率[^，。]*下降\d+(?:\.\d+)?个百分点)", text)
            if margin:
                children.append(f"{margin.group(1)}对公司毛利率产生负面影响")
                children.append(margin.group(2))

        # Preserve combined causes and the outcome; do not assign the full
        # outcome magnitude to either individual cause.
        if text.startswith("由于") and "和" in text and "毛利率" in text and "下降" in text:
            outcome = re.search(r"([^，。]+毛利率[^，。]*下降\d+(?:\.\d+)?个百分点)", text)
            cause = re.match(r"由于(.+?)，", text)
            if cause and outcome:
                children = [
                    f"{cause.group(1)}共同对公司毛利率下降产生影响",
                    outcome.group(1),
                ]

        if not children:
            children = [text]

        result: list[ChildFact] = []
        for index, child_text in enumerate(dict.fromkeys(children), 1):
            offset = text.find(child_text)
            # Generated causal summaries are not literal source spans. Keep
            # them traceable to the complete Parent instead of inventing an
            # out-of-range offset.
            source_start = parent.source_start + offset if offset >= 0 else parent.source_start
            source_end = source_start + len(child_text) if offset >= 0 else parent.source_end
            result.append(
                ChildFact(
                    fact_id=f"{parent.parent_id.replace('P', 'F')}{index:02d}",
                    parent_id=parent.parent_id,
                    fact=child_text,
                    source_start=source_start,
                    source_end=source_end,
                )
            )
        return result


class SimpleCompanyResolver:
    def __init__(self, companies: dict[str, dict[str, str]] | None = None) -> None:
        self.companies = companies or {}

    def resolve(self, original_input: str) -> dict[str, Any] | None:
        for name, info in self.companies.items():
            stock_code = info.get("stock_code")
            if name in original_input or (stock_code and stock_code in original_input):
                return {
                    "company_name": name,
                    "stock_code": info.get("stock_code"),
                    "resolution_method": "deterministic",
                }
        return None


class SimpleQueryPlanner:
    def plan(self, child: dict[str, Any], parent: dict[str, Any], company: dict[str, Any] | None, attempt: int) -> list[dict[str, Any]]:
        fact = child["fact"]
        query = fact if attempt == 0 else f"{fact}；原始语境：{parent['parent_text']}"
        evidence_type = "table" if re.search(r"收入|利润|毛利率|资产负债率|比例|同比|金额|数值", fact) else "text"
        return [{
            "query_id": f"Q-{child['fact_id']}-{attempt}",
            "fact_id": child["fact_id"],
            "query_text": query,
            "retrieval_type": evidence_type,
            "attempt": attempt,
            "company": company,
        }]

    def rewrite(self, child: dict[str, Any], parent: dict[str, Any], previous_queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.plan(child, parent, None, len(previous_queries))


class InMemoryEvidenceRetriever:
    def __init__(self, evidence: list[Evidence], scope: dict[str, Any] | None = None) -> None:
        self.evidence = evidence
        self.scope = scope

    def retrieve(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        query_text = query["query_text"]
        ranked: list[tuple[float, Evidence]] = []
        for item in self.evidence:
            if self.scope:
                allowed_documents = set(self.scope.get("allowed_document_ids", []))
                allowed_companies = set(self.scope.get("company_ids", []))
                allowed_periods = set(self.scope.get("periods", []))
                if allowed_documents and item.document_id not in allowed_documents:
                    continue
                if allowed_companies and item.company_id not in allowed_companies:
                    continue
                if allowed_periods and item.period not in allowed_periods:
                    continue
            score = self._score(query_text, item.content)
            if score > 0:
                ranked.append((score, item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [asdict(item) | {"score": round(score, 4), "query_id": query["query_id"]} for score, item in ranked[:5]]

    @staticmethod
    def _score(query: str, content: str) -> float:
        if query.strip() and query.strip() in content:
            return 1.0
        query_terms = set(re.findall(r"[A-Za-z0-9%]+|[\u4e00-\u9fff]{2}", query))
        content_terms = set(re.findall(r"[A-Za-z0-9%]+|[\u4e00-\u9fff]{2}", content))
        return len(query_terms & content_terms) / max(len(query_terms), 1)


class MvpEvidenceGrader:
    def grade(self, child: dict[str, Any], evidence: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], EvidenceStatus]:
        assessments: list[dict[str, Any]] = []
        fact = child["fact"]
        for item in evidence:
            content = item["content"]
            relation = "IRRELEVANT"
            rationale = "与 Child 的可识别信息重合不足。"
            if self._contradicts(fact, content):
                relation = "CONTRADICTS"
                rationale = "证据中的方向或数值与 Child 不一致。"
            elif self._qualitative_support(fact, content):
                relation = "SUPPORTS"
                rationale = "证据提供了该定性判断对应的财务指标或原文解释。"
            elif item.get("score", 0) >= 0.45:
                relation = "SUPPORTS"
                rationale = "证据包含 Child 的主体、指标、期间或数值信息。"
            elif item.get("score", 0) >= 0.2:
                relation = "PARTIALLY_SUPPORTS"
                rationale = "证据部分相关，但不足以单独支持完整 Child。"
            assessments.append(asdict(EvidenceAssessment(item["evidence_id"], relation, rationale, relation != "IRRELEVANT")))

        relations = {item["relation"] for item in assessments}
        if "SUPPORTS" in relations or "CONTRADICTS" in relations:
            status: EvidenceStatus = "SUFFICIENT"
        elif "PARTIALLY_SUPPORTS" in relations:
            status = "PARTIAL"
        else:
            status = "INSUFFICIENT"
        return assessments, status

    @staticmethod
    def _qualitative_support(fact: str, content: str) -> bool:
        """Recognize indicator evidence for qualitative finance claims.

        This does not decide whether the metric is good or bad.  It only
        connects a qualitative concept to an observed indicator so the later
        verifier and business rules can make the directional judgment.
        """

        concept_indicators = {
            "偿债能力": ("流动比率", "速动比率", "资产负债率", "利息保障倍数", "经营现金流"),
            "流动性": ("流动比率", "速动比率", "现金比率", "流动性覆盖率", "现金"),
            "盈利能力": ("毛利率", "净利率", "净利润", "净资产收益率", "ROE", "ROA"),
            "成长性": ("收入增长", "营业收入", "同比增长", "增速", "净利润增长"),
            "增长能力": ("收入增长", "营业收入", "同比增长", "增速", "净利润增长"),
            "现金流质量": ("经营现金流", "经营活动现金流", "现金含量", "自由现金流"),
            "营运能力": ("周转率", "周转天数", "存货", "应收账款"),
            "运营效率": ("周转率", "周转天数", "资产周转"),
            "杠杆": ("资产负债率", "产权比率", "有息负债", "利息保障倍数"),
            "负债风险": ("资产负债率", "债务", "利息保障倍数"),
            "经营稳定性": ("收入", "客户集中度", "订单", "波动"),
            "业务稳定性": ("收入", "客户集中度", "订单", "波动"),
            "竞争力": ("市场份额", "行业地位", "毛利率", "研发"),
            "市场地位": ("市场份额", "行业地位", "竞争"),
            "治理": ("审计意见", "内部控制", "关联交易", "诉讼"),
            "合规": ("审计意见", "内部控制", "处罚", "诉讼"),
        }
        for concept, indicators in concept_indicators.items():
            if concept in fact and any(indicator.lower() in content.lower() for indicator in indicators):
                return True
        return False

    @staticmethod
    def _contradicts(fact: str, content: str) -> bool:
        metric_groups = (
            ("营业收入", "收入"),
            ("利润",),
            ("毛利率",),
            ("资产负债率",),
            ("流动比率",),
            ("速动比率",),
            ("现金流",),
        )
        same_metric = any(
            any(term in fact for term in group)
            and any(term in content for term in group)
            for group in metric_groups
        )
        if not same_metric:
            return False
        fact_claim = MvpEvidenceGrader._metric_claim(fact)
        content_claim = MvpEvidenceGrader._metric_claim(content)
        if fact_claim is None or content_claim is None:
            return False
        fact_kind, fact_direction, fact_value, fact_unit = fact_claim
        content_kind, content_direction, content_value, content_unit = content_claim
        if fact_kind != content_kind:
            return False
        if fact_kind == "change":
            return fact_direction != content_direction or fact_value != content_value or (fact_unit and content_unit and fact_unit != content_unit)
        return fact_value != content_value or (fact_unit and content_unit and fact_unit != content_unit)

    @staticmethod
    def _metric_claim(text: str) -> tuple[str, str | None, str, str | None] | None:
        """Return only the number attached to the matched metric.

        Years, stock codes and unrelated amounts must not make supporting
        evidence look contradictory.
        """
        metrics = ("营业收入", "收入", "利润", "毛利率", "资产负债率", "流动比率", "速动比率", "现金流")
        metric = next((item for item in metrics if item in text), None)
        if metric is None:
            return None
        tail = text[text.find(metric) :]
        change = re.search(r"(?:同比|环比)?\s*(增长|下降|上升|减少)\s*(-?\d+(?:\.\d+)?)\s*(%|个百分点|个百分[点])?", tail)
        if change:
            direction = "下降" if change.group(1) in {"下降", "减少"} else "增长"
            return "change", direction, change.group(2), change.group(3)
        value = re.search(r"(?:为|是)\s*(-?\d+(?:\.\d+)?)\s*(%|个百分点|个百分[点])?", tail)
        if value:
            return "value", None, value.group(1), value.group(2)
        return None


class MvpFactVerifier:
    def verify(self, child: dict[str, Any], parent: dict[str, Any], evidence: list[dict[str, Any]], assessments: list[dict[str, Any]], evidence_status: EvidenceStatus) -> dict[str, Any]:
        del parent  # Parent is context only; never an Evidence input.
        usable = [a for a in assessments if a["usable"]]
        support_ids = [a["evidence_id"] for a in usable if a["relation"] == "SUPPORTS"]
        contradiction_ids = [a["evidence_id"] for a in usable if a["relation"] == "CONTRADICTS"]
        if evidence_status == "INSUFFICIENT" or not evidence:
            result = VerificationResult("INSUFFICIENT_EVIDENCE", "没有检索到足以核验该 Child 的外部证据。", [], "low")
        elif support_ids and contradiction_ids:
            result = VerificationResult(
                "INSUFFICIENT_EVIDENCE", "同时存在支持和反向证据，当前无法安全判定。",
                support_ids + contradiction_ids, "low", contradiction_ids,
                ["risk_omission"], ["support and counter evidence conflict"],
            )
        elif contradiction_ids:
            result = VerificationResult("CONTRADICTED", "外部证据与 Child 的方向或数值不一致。", contradiction_ids, "high", contradiction_ids)
        elif support_ids:
            result = VerificationResult("SUPPORTED", "外部证据与 Child 的主体、指标、期间或数值一致。", support_ids, "medium")
        else:
            result = VerificationResult("INSUFFICIENT_EVIDENCE", "证据仅部分相关，不能支持完整 Child。", [], "low")
        return asdict(result)
