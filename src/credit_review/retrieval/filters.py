"""Authorization filters applied before retrieval scoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def filter_by_scope(candidates: Sequence[Mapping[str, Any]], scope: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if scope is None:
        return [dict(item) for item in candidates]
    allowed_documents = set(scope.get("allowed_document_ids", []))
    allowed_companies = set(scope.get("company_ids", []))
    allowed_periods = set(scope.get("periods", []))
    allowed_types = set(scope.get("evidence_types", []))
    filtered: list[dict[str, Any]] = []
    for item in candidates:
        document_id = item.get("document_id") or item.get("locator", {}).get("document_id")
        company_id = item.get("company_id")
        period = item.get("period")
        if allowed_documents and document_id not in allowed_documents:
            continue
        if allowed_companies and company_id not in allowed_companies:
            continue
        if allowed_periods and period not in allowed_periods:
            continue
        if allowed_types and str(item.get("evidence_type", "text")) not in allowed_types:
            continue
        filtered.append(dict(item))
    return filtered
