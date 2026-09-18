"""Citation checks. Missing page numbers are valid; fabricated locations are not."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def citation_is_traceable(evidence: Mapping[str, Any]) -> bool:
    locator = evidence.get("locator", evidence)
    document_id = locator.get("document_id")
    version = locator.get("document_version")
    if not document_id or not version:
        return False
    content = evidence.get("content")
    expected_hash = locator.get("content_hash")
    return not expected_hash or (isinstance(content, str) and expected_hash == content_hash(content))


def validate_citations(evidence: list[Mapping[str, Any]]) -> list[str]:
    return [str(item["evidence_id"]) for item in evidence if not citation_is_traceable(item)]
