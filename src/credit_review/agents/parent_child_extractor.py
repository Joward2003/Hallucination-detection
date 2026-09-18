from __future__ import annotations

from typing import Any

from credit_review.services.mvp_services import DeterministicParentChildExtractor


class ParentChildExtractor(DeterministicParentChildExtractor):
    """Stable extractor port with the provider-free implementation as default."""

    def extract(self, original_input: str, context: Any | None = None) -> list[dict[str, Any]]:
        del context
        return super().extract(original_input)
