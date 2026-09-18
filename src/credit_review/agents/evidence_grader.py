from __future__ import annotations

from typing import Any, Sequence

from credit_review.services.mvp_services import MvpEvidenceGrader


class EvidenceGrader(MvpEvidenceGrader):
    def grade(self, child: dict[str, Any], parent: dict[str, Any] | None, evidence: Sequence[dict[str, Any]] | None = None):
        del parent
        return super().grade(child, list(evidence or []))
