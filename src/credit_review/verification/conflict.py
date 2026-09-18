from __future__ import annotations

from collections.abc import Iterable, Mapping


def has_conflict(assessments: Iterable[Mapping[str, object]]) -> bool:
    relations = {str(item.get("relation")) for item in assessments if item.get("usable", True)}
    return "SUPPORTS" in relations and "CONTRADICTS" in relations
