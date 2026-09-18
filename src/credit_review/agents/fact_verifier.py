from __future__ import annotations

from typing import Any, Sequence

from credit_review.services.mvp_services import MvpFactVerifier


class FactVerifier(MvpFactVerifier):
    """Verifier port; Parent is accepted as context and never searched as evidence."""

    def verify(self, child: dict[str, Any], parent: dict[str, Any], evidence: Sequence[dict[str, Any]], assessments: Sequence[dict[str, Any]], evidence_status: str = "INSUFFICIENT") -> dict[str, Any]:
        return super().verify(child, parent, list(evidence), list(assessments), evidence_status)
