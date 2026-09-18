from __future__ import annotations

import os
from dataclasses import dataclass

from .models import DeepSeekConfig, RetrievalConfig


@dataclass(frozen=True)
class Settings:
    max_retrieval_attempts: int = 2
    external_llm_allowed_classifications: tuple[str, ...] = ()
    evidence_excerpt_max_length: int = 2000
    corpus_version: str | None = None
    rule_set_version: str = "default"
    deepseek: DeepSeekConfig = DeepSeekConfig()
    retrieval: RetrievalConfig = RetrievalConfig()

    @classmethod
    def from_env(cls) -> "Settings":
        attempts = int(os.getenv("CREDIT_REVIEW_MAX_RETRIEVAL_ATTEMPTS", "2"))
        if attempts < 1:
            raise ValueError("max retrieval attempts must be >= 1")
        max_length = int(os.getenv("CREDIT_REVIEW_EVIDENCE_EXCERPT_MAX_LENGTH", "2000"))
        if max_length < 1:
            raise ValueError("evidence excerpt max length must be >= 1")
        allowed = tuple(item for item in os.getenv("CREDIT_REVIEW_EXTERNAL_LLM_ALLOWED_CLASSIFICATIONS", "").split(",") if item)
        return cls(
            max_retrieval_attempts=attempts,
            external_llm_allowed_classifications=allowed,
            evidence_excerpt_max_length=max_length,
            corpus_version=os.getenv("CREDIT_REVIEW_CORPUS_VERSION"),
            rule_set_version=os.getenv("CREDIT_REVIEW_RULE_SET_VERSION", "default"),
            deepseek=DeepSeekConfig.from_env(),
            retrieval=RetrievalConfig.from_env(),
        )
