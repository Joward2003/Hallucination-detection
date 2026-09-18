from __future__ import annotations

from .fact_verifier import FactVerifier


class CriticVerifier(FactVerifier):
    """Independent invocation surface; it receives no initial verdict argument."""

    def verify_independently(self, child, parent, evidence, assessments, evidence_status):
        return self.verify(child, parent, evidence, assessments, evidence_status)
