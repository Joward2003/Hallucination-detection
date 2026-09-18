from __future__ import annotations

from collections.abc import Iterable, Mapping


def evidence_status_from_relations(relations: Iterable[str | Mapping[str, object]]) -> str:
    values = {item if isinstance(item, str) else str(item.get("relation")) for item in relations}
    if "SUPPORTS" in values or "CONTRADICTS" in values:
        return "SUFFICIENT"
    if "PARTIALLY_SUPPORTS" in values:
        return "PARTIAL"
    return "INSUFFICIENT"
