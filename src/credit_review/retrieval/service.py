from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from math import log, sqrt
from typing import Any

from .filters import filter_by_scope


# The registry is intentionally small and deterministic for the MVP.  A
# production deployment can load the same shape from ``metrics/financial.yaml``
# without changing the retrieval worker contract.
FINANCIAL_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "current_assets": ("流动资产", "current assets", "current_assets"),
    "current_liabilities": ("流动负债", "current liabilities", "current_liabilities"),
    "quick_assets": ("速动资产", "quick assets", "quick_assets"),
    "inventory": ("存货", "inventory"),
    "prepayments": ("预付款项", "预付账款", "prepayments"),
    "total_liabilities": ("负债合计", "总负债", "total liabilities", "total_liabilities"),
    "total_assets": ("资产总计", "总资产", "total assets", "total_assets"),
    "revenue": ("营业收入", "主营业务收入", "收入", "revenue"),
    "revenue_growth": ("收入增长", "营业收入增长", "同比增长", "增速", "revenue growth", "revenue_growth"),
    "net_profit": ("净利润", "归母净利润", "利润", "net profit", "net_profit"),
    "profit_growth": ("利润增长", "净利润增长", "profit growth", "profit_growth"),
    "asset_growth": ("资产增长", "总资产增长", "asset growth", "asset_growth"),
    "gross_margin": ("毛利率", "gross margin", "gross_margin"),
    "net_margin": ("净利率", "net margin", "net_margin"),
    "roe": ("净资产收益率", "roe"),
    "roa": ("总资产报酬率", "资产回报率", "roa"),
    "cash_ratio": ("现金比率", "cash ratio", "cash_ratio"),
    "cash": ("货币资金", "现金及现金等价物", "cash"),
    "operating_cash_flow": ("经营活动现金流净额", "经营现金流", "operating cash flow", "operating_cash_flow"),
    "interest_bearing_debt": ("有息负债", "interest bearing debt", "interest_bearing_debt"),
    "asset_turnover": ("总资产周转率", "asset turnover", "asset_turnover"),
    "inventory_turnover": ("存货周转率", "inventory turnover", "inventory_turnover"),
    "receivables_turnover": ("应收账款周转率", "receivables turnover", "receivables_turnover"),
    "accounts_receivable": ("应收账款", "accounts receivable", "accounts_receivable"),
    "debt_to_equity": ("产权比率", "负债权益比", "debt to equity", "debt_to_equity"),
    "revenue_volatility": ("收入波动", "revenue volatility", "revenue_volatility"),
    "customer_concentration": ("客户集中度", "customer concentration", "customer_concentration"),
    "segment_revenue": ("分部收入", "segment revenue", "segment_revenue"),
    "market_share": ("市场份额", "market share", "market_share"),
    "rd_intensity": ("研发费用率", "研发投入", "rd intensity", "rd_intensity"),
    "ebit": ("息税前利润", "ebit"),
    "interest_expense": ("利息费用", "interest expense", "interest_expense"),
    "current_ratio": ("流动比率", "current ratio", "current_ratio"),
    "quick_ratio": ("速动比率", "quick ratio", "quick_ratio"),
    "debt_to_assets": ("资产负债率", "debt to assets", "debt_to_assets"),
    "interest_coverage": ("利息保障倍数", "interest coverage", "interest_coverage"),
    "liquidity_coverage_ratio": ("流动性覆盖率", "liquidity coverage ratio", "liquidity_coverage_ratio"),
    "net_stable_funding_ratio": ("净稳定资金比例", "净稳定资金比率", "net stable funding ratio", "net_stable_funding_ratio"),
    "capital_adequacy_ratio": ("资本充足率", "capital adequacy ratio", "capital_adequacy_ratio"),
    "cet1_ratio": ("核心一级资本充足率", "cet1 ratio", "cet1_ratio"),
    "solvency_adequacy_ratio": ("偿付能力充足率", "solvency adequacy ratio", "solvency_adequacy_ratio"),
}


def _bounded_top_k(value: Any, default: int, *, maximum: int = 200) -> int:
    """Normalize a caller supplied Top-k and reject unsafe values.

    Planning Agent output is untrusted at the retrieval boundary.  Keeping a
    single bound here prevents a malformed plan or API request from turning a
    local worker into an unbounded scan, while still allowing providers to
    replace the deterministic workers behind the same contract.
    """

    raw = default if value is None else value
    try:
        top_k = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"top_k must be an integer between 1 and {maximum}") from exc
    if top_k < 1 or top_k > maximum:
        raise ValueError(f"top_k must be between 1 and {maximum}")
    return top_k


def _candidate_dict(item: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Normalize legacy Evidence dataclasses and mapping candidates."""

    if isinstance(item, Mapping):
        return dict(item)
    if is_dataclass(item):
        return asdict(item)
    raise TypeError("retrieval candidates must be mappings or dataclass records")


class ScopedInMemoryRetriever:
    """Deterministic retriever used by tests and local development."""

    def __init__(self, candidates: list[Mapping[str, Any]], top_k: int = 12) -> None:
        self.candidates = [_candidate_dict(item) for item in candidates]
        self.top_k = top_k

    def retrieve(self, query: Mapping[str, Any], scope: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        query_text = str(query.get("query_text", ""))
        query_terms = set(re.findall(r"[A-Za-z0-9%]+|[\u4e00-\u9fff]{2}", query_text))
        ranked: list[tuple[float, dict[str, Any]]] = []
        seen: set[str] = set()
        # Scope filtering deliberately happens before scoring.
        for candidate in filter_by_scope(self.candidates, scope):
            evidence_id = str(candidate.get("evidence_id", ""))
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            content_terms = set(re.findall(r"[A-Za-z0-9%]+|[\u4e00-\u9fff]{2}", str(candidate.get("content", ""))))
            score = len(query_terms & content_terms) / max(len(query_terms), 1)
            if query_text.strip() and query_text.strip() in str(candidate.get("content", "")):
                score = 1.0
            if score > 0:
                result = dict(candidate)
                result["retrieval_score"] = round(score, 4)
                result["query_id"] = query.get("query_id")
                ranked.append((score, result))
        ranked.sort(key=lambda pair: (-pair[0], str(pair[1].get("evidence_id", ""))))
        return [item for _, item in ranked[: self.top_k]]


def financial_tokens(text: str) -> list[str]:
    """Tokenize Chinese and financial text without dropping numbers or units.

    The tokenizer is deliberately shared by BM25, the deterministic dense
    adapter and the reranker.  A production tokenizer can be injected later,
    but query and index tokenization must remain identical.
    """

    value = str(text or "").lower()
    tokens: list[str] = re.findall(r"[a-z0-9_.%+-]+", value)
    chinese = re.findall(r"[\u4e00-\u9fff]", value)
    tokens.extend(chinese)
    tokens.extend("".join(chinese[index : index + 2]) for index in range(len(chinese) - 1))
    return tokens


def infer_metric_ids(candidate: Mapping[str, Any]) -> set[str]:
    """Return registry metric IDs attached to or inferred from a candidate."""

    explicit = candidate.get("metric_ids") or candidate.get("metrics") or []
    if isinstance(explicit, str):
        explicit = [explicit]
    metric_ids = {str(item) for item in explicit if item}
    if candidate.get("metric_id"):
        metric_ids.add(str(candidate["metric_id"]))
    content = str(candidate.get("content", "")).lower()
    for metric_id, aliases in FINANCIAL_METRIC_ALIASES.items():
        if any(alias.lower() in content for alias in aliases):
            metric_ids.add(metric_id)
    return metric_ids


def infer_periods(candidate: Mapping[str, Any]) -> set[str]:
    """Read normalized periods from metadata and financial text."""

    values = candidate.get("periods") or []
    if isinstance(values, str):
        values = [values]
    periods = {str(item) for item in values if item}
    if candidate.get("period"):
        periods.add(str(candidate["period"]))
    periods.update(re.findall(r"20\d{2}", str(candidate.get("content", ""))))
    return periods


class DeterministicDenseRetriever:
    """Provider-free dense-like retriever used for local tests and demos.

    It hashes shared financial tokens into a fixed vector and computes cosine
    similarity.  This is an adapter seam, not a claim that hashing matches a
    neural embedding model; replace it with BGE-M3/another embedding service
    without changing the hybrid service contract.
    """

    def __init__(self, candidates: list[Mapping[str, Any]], top_k: int = 50, dimensions: int = 256) -> None:
        self.candidates = [_candidate_dict(item) for item in candidates]
        self.top_k = _bounded_top_k(top_k, 50)
        self.dimensions = dimensions

    def retrieve(self, query: str, scope: Mapping[str, Any] | None = None, top_k: int | None = None) -> list[dict[str, Any]]:
        ranked: list[tuple[float, dict[str, Any]]] = []
        for candidate in filter_by_scope(self.candidates, scope):
            score = self._cosine(query, str(candidate.get("content", "")))
            if score <= 0:
                continue
            item = dict(candidate)
            item.update({"route": "dense", "retrieval_score": round(score, 6)})
            ranked.append((score, item))
        ranked.sort(key=lambda pair: (-pair[0], str(pair[1].get("evidence_id", ""))))
        return [item for _, item in ranked[: _bounded_top_k(top_k, self.top_k)]]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in financial_tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimensions
            vector[index] += 1.0
        return vector

    def _cosine(self, left: str, right: str) -> float:
        left_vector = self._vector(left)
        right_vector = self._vector(right)
        dot = sum(a * b for a, b in zip(left_vector, right_vector))
        left_norm = sqrt(sum(value * value for value in left_vector))
        right_norm = sqrt(sum(value * value for value in right_vector))
        return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


class BM25Retriever:
    """Small in-process BM25 index with scope filtering before scoring."""

    def __init__(self, candidates: list[Mapping[str, Any]], top_k: int = 50, k1: float = 1.5, b: float = 0.75) -> None:
        self.candidates = [_candidate_dict(item) for item in candidates]
        self.top_k = _bounded_top_k(top_k, 50)
        self.k1 = k1
        self.b = b
        self._tokens = [financial_tokens(str(item.get("content", ""))) for item in self.candidates]
        self._avgdl = sum(len(tokens) for tokens in self._tokens) / max(len(self._tokens), 1)
        self._document_frequency: dict[str, int] = {}
        for tokens in self._tokens:
            for token in set(tokens):
                self._document_frequency[token] = self._document_frequency.get(token, 0) + 1

    def retrieve(self, query: str, scope: Mapping[str, Any] | None = None, top_k: int | None = None) -> list[dict[str, Any]]:
        query_tokens = financial_tokens(query)
        allowed = filter_by_scope(self.candidates, scope)
        allowed_ids = {str(item.get("evidence_id", "")) for item in allowed}
        document_count = max(len(self.candidates), 1)
        ranked: list[tuple[float, dict[str, Any]]] = []
        for index, candidate in enumerate(self.candidates):
            if str(candidate.get("evidence_id", "")) not in allowed_ids:
                continue
            tokens = self._tokens[index]
            frequencies: dict[str, int] = {}
            for token in tokens:
                frequencies[token] = frequencies.get(token, 0) + 1
            score = 0.0
            for token in query_tokens:
                frequency = frequencies.get(token, 0)
                if not frequency:
                    continue
                df = self._document_frequency.get(token, 0)
                idf = log(1.0 + (document_count - df + 0.5) / (df + 0.5))
                denominator = frequency + self.k1 * (1 - self.b + self.b * len(tokens) / max(self._avgdl, 1e-9))
                score += idf * frequency * (self.k1 + 1) / denominator
            if score <= 0:
                continue
            item = dict(candidate)
            item.update({"route": "bm25", "retrieval_score": round(score, 6)})
            ranked.append((score, item))
        ranked.sort(key=lambda pair: (-pair[0], str(pair[1].get("evidence_id", ""))))
        return [item for _, item in ranked[: _bounded_top_k(top_k, self.top_k)]]


class TableLookupRetriever:
    """Metadata-aware table worker for financial statement evidence.

    Table lookup is deliberately separate from text search.  It first applies
    the authorization scope and then scores requested metric IDs and periods.
    This prevents a narrative paragraph that happens to mention a ratio from
    being presented as the authoritative table cell.
    """

    def __init__(self, candidates: list[Mapping[str, Any]], top_k: int = 20) -> None:
        self.candidates = [_candidate_dict(item) for item in candidates]
        self.top_k = _bounded_top_k(top_k, 20)

    def retrieve(
        self,
        query: Mapping[str, Any] | str,
        scope: Mapping[str, Any] | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        if isinstance(query, str):
            query_data: Mapping[str, Any] = {"query_text": query}
        else:
            query_data = query
        requested_metrics = {str(item) for item in (query_data.get("metric_ids") or []) if item}
        requested_periods = {str(item) for item in (query_data.get("periods") or []) if item and item != "latest"}
        query_text = str(query_data.get("query_text", ""))
        ranked: list[tuple[float, dict[str, Any]]] = []
        for candidate in filter_by_scope(self.candidates, scope):
            if str(candidate.get("evidence_type", "text")) != "table":
                continue
            metric_ids = infer_metric_ids(candidate)
            periods = infer_periods(candidate)
            metric_overlap = len(requested_metrics & metric_ids) / max(len(requested_metrics), 1)
            period_overlap = len(requested_periods & periods) / max(len(requested_periods), 1) if requested_periods else 0.0
            lexical = len(set(financial_tokens(query_text)) & set(financial_tokens(str(candidate.get("content", ""))))) / max(len(set(financial_tokens(query_text))), 1)
            # Metric and period matches dominate lexical similarity.  A query
            # with no explicit metric falls back to lexical table search.
            score = 0.65 * metric_overlap + 0.25 * period_overlap + 0.10 * lexical if requested_metrics else lexical
            if score <= 0 or (requested_metrics and not (requested_metrics & metric_ids)):
                continue
            item = dict(candidate)
            item.update({
                "route": "table",
                "retrieval_score": round(score, 6),
                "rerank_score": round(score, 6),
                "score": round(score, 6),
                "matched_metric_ids": sorted(requested_metrics & metric_ids),
                "matched_periods": sorted(requested_periods & periods),
            })
            ranked.append((score, item))
        ranked.sort(key=lambda pair: (-pair[0], str(pair[1].get("evidence_id", ""))))
        requested_top_k = query_data.get("table_top_k", top_k)
        return [item for _, item in ranked[: _bounded_top_k(requested_top_k, self.top_k)]]


class StructuredDataRetriever:
    """Worker for normalized metric records and explicitly structured rows."""

    def __init__(self, candidates: list[Mapping[str, Any]], top_k: int = 20) -> None:
        self.candidates = [_candidate_dict(item) for item in candidates]
        self.top_k = _bounded_top_k(top_k, 20)

    def retrieve(
        self,
        query: Mapping[str, Any] | str,
        scope: Mapping[str, Any] | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        query_data: Mapping[str, Any] = {"query_text": query} if isinstance(query, str) else query
        requested_metrics = {str(item) for item in (query_data.get("metric_ids") or []) if item}
        requested_periods = {str(item) for item in (query_data.get("periods") or []) if item and item != "latest"}
        ranked: list[tuple[float, dict[str, Any]]] = []
        for candidate in filter_by_scope(self.candidates, scope):
            metric_ids = infer_metric_ids(candidate)
            is_structured = bool(candidate.get("structured")) or bool(candidate.get("metric_id")) or bool(candidate.get("metric_ids"))
            if not is_structured:
                continue
            if requested_metrics and not (requested_metrics & metric_ids):
                continue
            periods = infer_periods(candidate)
            metric_score = len(requested_metrics & metric_ids) / max(len(requested_metrics), 1) if requested_metrics else 1.0
            period_score = len(requested_periods & periods) / max(len(requested_periods), 1) if requested_periods else 1.0
            score = 0.7 * metric_score + 0.3 * period_score
            item = dict(candidate)
            item.update({
                "route": "structured",
                "retrieval_score": round(score, 6),
                "rerank_score": round(score, 6),
                "score": round(score, 6),
                "matched_metric_ids": sorted(requested_metrics & metric_ids),
                "matched_periods": sorted(requested_periods & periods),
            })
            ranked.append((score, item))
        ranked.sort(key=lambda pair: (-pair[0], str(pair[1].get("evidence_id", ""))))
        requested_top_k = query_data.get("structured_top_k", top_k)
        return [item for _, item in ranked[: _bounded_top_k(requested_top_k, self.top_k)]]


class RetrievalRouter:
    """Dispatch one Planning Agent request to the appropriate retrieval worker."""

    def __init__(
        self,
        candidates: list[Mapping[str, Any]],
        *,
        text_search: HybridSearchService | None = None,
        table_search: TableLookupRetriever | None = None,
        structured_search: StructuredDataRetriever | None = None,
        default_scope: Mapping[str, Any] | None = None,
    ) -> None:
        # HybridSearchService is defined below; defer construction until this
        # class is instantiated, after module import has completed.
        self.text_search = text_search or HybridSearchService(candidates, default_scope=default_scope)
        self.table_search = table_search or TableLookupRetriever(candidates)
        self.structured_search = structured_search or StructuredDataRetriever(candidates)
        self.default_scope = dict(default_scope or {})

    def retrieve(self, query: Mapping[str, Any], scope: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        scope = self.default_scope if scope is None else scope
        profile = str(query.get("retrieval_profile") or query.get("retrieval_type") or "atomic_text")
        if profile in {"financial_table", "table", "table_lookup"}:
            hits = self.table_search.retrieve(query, scope)
            # Some legacy evidence exports did not label their type.  Preserve
            # recall with a bounded text fallback, while retaining the worker
            # route in the trace so callers can distinguish it from a table hit.
            if not hits:
                hits = self.text_search.retrieve(query, scope)
                for item in hits:
                    item["route"] = "table_fallback"
        elif profile in {"structured_data", "structured", "metric_lookup"}:
            hits = self.structured_search.retrieve(query, scope)
        elif profile in {"hybrid", "table_and_text"}:
            table_hits = self.table_search.retrieve(query, scope)
            text_hits = self.text_search.retrieve(query, scope)
            by_id: dict[str, dict[str, Any]] = {}
            for item in table_hits + text_hits:
                evidence_id = str(item.get("evidence_id", ""))
                if evidence_id and evidence_id not in by_id:
                    by_id[evidence_id] = item
            hits = list(by_id.values())
        else:
            hits = self.text_search.retrieve(query, scope)
        for item in hits:
            item.setdefault("query_id", query.get("query_id"))
            item.setdefault("retrieval_profile", profile)
        return hits

    search = retrieve


class RRFFusion:
    """Fuse ranked routes without comparing incompatible raw score scales."""

    def __init__(self, rrf_k: int = 60, route_weights: Mapping[str, float] | None = None) -> None:
        self.rrf_k = rrf_k
        self.route_weights = dict(route_weights or {"dense": 1.0, "bm25": 1.0})

    def fuse(self, routes: Mapping[str, list[Mapping[str, Any]]], top_k: int = 60) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for route, items in routes.items():
            weight = float(self.route_weights.get(route, 1.0))
            for rank, item in enumerate(items, 1):
                evidence_id = str(item.get("evidence_id", ""))
                if not evidence_id:
                    continue
                target = merged.setdefault(evidence_id, {**dict(item), "route_hits": []})
                target["route_hits"].append({"route": route, "rank": rank, "raw_score": item.get("retrieval_score")})
                target["rrf_score"] = float(target.get("rrf_score", 0.0)) + weight / (self.rrf_k + rank)
        ranked = sorted(merged.values(), key=lambda item: (-float(item.get("rrf_score", 0.0)), str(item.get("evidence_id", ""))))
        for rank, item in enumerate(ranked[:top_k], 1):
            item["rank"] = rank
        return ranked[:_bounded_top_k(top_k, 60)]


class DeterministicReranker:
    """Cross-encoder seam with a transparent lexical fallback."""

    def rank(self, query: str, candidates: list[Mapping[str, Any]], top_n: int = 12) -> list[dict[str, Any]]:
        query_tokens = financial_tokens(query)
        query_set = set(query_tokens)
        ranked: list[tuple[float, dict[str, Any]]] = []
        for candidate in candidates:
            content = str(candidate.get("content", ""))
            content_tokens = financial_tokens(content)
            overlap = len(query_set & set(content_tokens)) / max(len(query_set), 1)
            phrase_bonus = 0.25 if query.strip() and query.strip().lower() in content.lower() else 0.0
            number_tokens = {token for token in query_tokens if re.search(r"\d", token)}
            number_bonus = 0.15 if number_tokens and number_tokens <= set(content_tokens) else 0.0
            score = min(1.0, 0.6 * overlap + phrase_bonus + number_bonus)
            item = dict(candidate)
            item["rerank_score"] = round(score, 6)
            item["score"] = item["rerank_score"]
            ranked.append((score, item))
        ranked.sort(key=lambda pair: (-pair[0], -float(pair[1].get("rrf_score", 0.0)), str(pair[1].get("evidence_id", ""))))
        return [item for _, item in ranked[:_bounded_top_k(top_n, 12)]]


class HybridSearchService:
    """Dense/BM25 retrieval, RRF fusion and reranking in one stable port."""

    def __init__(
        self,
        candidates: list[Mapping[str, Any]],
        *,
        dense_top_k: int = 50,
        bm25_top_k: int = 50,
        candidate_top_k: int = 60,
        rerank_top_n: int = 12,
        rrf_k: int = 60,
        default_scope: Mapping[str, Any] | None = None,
        dense_retriever: Any | None = None,
        lexical_retriever: Any | None = None,
        reranker: Any | None = None,
    ) -> None:
        self.candidates = [_candidate_dict(item) for item in candidates]
        self.dense_top_k = _bounded_top_k(dense_top_k, 50)
        self.bm25_top_k = _bounded_top_k(bm25_top_k, 50)
        self.candidate_top_k = _bounded_top_k(candidate_top_k, 60)
        self.rerank_top_n = _bounded_top_k(rerank_top_n, 12)
        self.default_scope = dict(default_scope or {})
        self.dense = dense_retriever or DeterministicDenseRetriever(self.candidates, top_k=dense_top_k)
        self.bm25 = lexical_retriever or BM25Retriever(self.candidates, top_k=bm25_top_k)
        self.fusion = RRFFusion(rrf_k=rrf_k)
        self.reranker = reranker or DeterministicReranker()

    def retrieve(self, query: Mapping[str, Any], scope: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        scope = self.default_scope if scope is None else scope
        expected_type = query.get("evidence_type")
        if expected_type == "text" and "evidence_types" not in scope:
            # Keep the concrete dense/BM25 adapters intact and add the type to
            # the pre-scoring authorization filter.  Rebuilding an index for
            # every narrative query would be both slow and incorrect for a
            # version-pinned production index.
            scope = {**scope, "evidence_types": ["text"]}
        query_text = str(query.get("query_text") or query.get("dense_query") or query.get("lexical_query") or "")
        dense_query = str(query.get("dense_query") or query_text)
        lexical_query = str(query.get("lexical_query") or query_text)
        dense_hits = self.dense.retrieve(dense_query, scope, top_k=_bounded_top_k(query.get("dense_top_k"), self.dense_top_k))
        bm25_hits = self.bm25.retrieve(lexical_query, scope, top_k=_bounded_top_k(query.get("lexical_top_k"), self.bm25_top_k))
        candidates = self.fusion.fuse(
            {"dense": dense_hits, "bm25": bm25_hits},
            top_k=_bounded_top_k(query.get("candidate_top_k"), self.candidate_top_k),
        )
        self.last_trace = {"query": dict(query), "scope": dict(scope), "dense_candidates": dense_hits, "bm25_candidates": bm25_hits, "fused_candidates": candidates}
        ranked = self.reranker.rank(
            query_text,
            candidates,
            top_n=_bounded_top_k(query.get("rerank_top_n"), self.rerank_top_n),
        )
        for item in ranked:
            item["query_id"] = query.get("query_id")
            item["retrieval_profile"] = query.get("retrieval_profile", "atomic_text")
        self.last_trace["ranked_candidates"] = ranked
        self.last_trace["all_rerank_scores"] = getattr(self.reranker, "last_scores", ranked)
        return ranked

    search = retrieve
