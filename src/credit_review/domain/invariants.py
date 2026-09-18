"""Pure validation for serializable domain payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .errors import DomainValidationError


def _required(mapping: Mapping[str, Any], name: str) -> Any:
    value = mapping.get(name)
    if value is None or value == "":
        raise DomainValidationError(f"missing required field: {name}")
    return value


def validate_fact_groups(groups: Sequence[Mapping[str, Any]]) -> None:
    if not isinstance(groups, Sequence) or isinstance(groups, (str, bytes)):
        raise DomainValidationError("fact_groups must be a sequence")
    parent_ids: set[str] = set()
    child_ids: set[str] = set()
    for group in groups:
        parent = _required(group, "parent")
        parent_id = str(_required(parent, "parent_id"))
        if parent_id in parent_ids:
            raise DomainValidationError(f"duplicate parent_id: {parent_id}")
        parent_ids.add(parent_id)
        start, end = int(_required(parent, "source_start")), int(_required(parent, "source_end"))
        if start < 0 or end < start:
            raise DomainValidationError(f"invalid parent span: {parent_id}")
        children = group.get("children")
        if not isinstance(children, Sequence) or isinstance(children, (str, bytes)) or not children:
            raise DomainValidationError(f"parent has no children: {parent_id}")
        for child in children:
            child_id = str(_required(child, "fact_id"))
            if child_id in child_ids:
                raise DomainValidationError(f"duplicate fact_id: {child_id}")
            child_ids.add(child_id)
            if str(_required(child, "parent_id")) != parent_id:
                raise DomainValidationError(f"child parent mismatch: {child_id}")
            child_start, child_end = int(_required(child, "source_start")), int(_required(child, "source_end"))
            if child_start < start or child_end < child_start or child_end > end:
                raise DomainValidationError(f"invalid child span: {child_id}")


def validate_verdict(verdict: Mapping[str, Any]) -> None:
    allowed = {"SUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE"}
    if _required(verdict, "status") not in allowed:
        raise DomainValidationError("invalid verdict status")
    if _required(verdict, "confidence_band") not in {"low", "medium", "high"}:
        raise DomainValidationError("invalid confidence band")


def validate_source_scope(scope: Mapping[str, Any]) -> None:
    for field in ("allowed_document_ids", "company_ids", "periods", "corpus_version", "rule_set_version"):
        _required(scope, field)
