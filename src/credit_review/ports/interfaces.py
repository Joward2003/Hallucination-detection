from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class Retriever(Protocol):
    def retrieve(self, query: Mapping[str, Any], scope: Mapping[str, Any] | None = None) -> list[dict[str, Any]]: ...


class EvidenceGrader(Protocol):
    def grade(self, child: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], str]: ...


class FactVerifier(Protocol):
    def verify(self, child: Mapping[str, Any], parent: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]], assessments: Sequence[Mapping[str, Any]], evidence_status: str) -> dict[str, Any]: ...
