"""Provider configuration loaded from environment variables only."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class DeepSeekConfig:
    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    api_key: str | None = field(default=None, repr=False)
    timeout_seconds: float = 60.0
    temperature: float = 0.0
    max_tokens: int = 2048

    @classmethod
    def from_env(cls, *, require_key: bool = False) -> "DeepSeekConfig":
        config = cls(
            model=os.getenv("DEEPSEEK_MODEL", cls.model),
            base_url=os.getenv("DEEPSEEK_BASE_URL", cls.base_url).rstrip("/"),
            api_key=os.getenv("DEEPSEEK_API_KEY") or None,
            timeout_seconds=float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", str(cls.timeout_seconds))),
            temperature=float(os.getenv("DEEPSEEK_TEMPERATURE", str(cls.temperature))),
            max_tokens=int(os.getenv("DEEPSEEK_MAX_TOKENS", str(cls.max_tokens))),
        )
        config.validate(require_key=require_key)
        return config

    def validate(self, *, require_key: bool = False) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("DEEPSEEK_BASE_URL must be an absolute http(s) URL")
        if not self.model.strip():
            raise ValueError("DEEPSEEK_MODEL must not be empty")
        if require_key and not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY is not set")
        if self.timeout_seconds <= 0 or self.max_tokens < 1:
            raise ValueError("DeepSeek timeout and max_tokens must be positive")
        if not 0 <= self.temperature <= 2:
            raise ValueError("DeepSeek temperature must be between 0 and 2")

    def safe_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self.model, "base_url": self.base_url, "timeout_seconds": self.timeout_seconds, "temperature": self.temperature, "max_tokens": self.max_tokens, "api_key_configured": bool(self.api_key)}


@dataclass(frozen=True)
class RetrievalConfig:
    """Runtime configuration for the production retrieval adapters."""

    backend: str = "deterministic"
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    embedding_revision: str | None = None
    reranker_revision: str | None = None
    device: str | None = None
    batch_size: int = 32
    local_files_only: bool = False
    bm25_backend: str = "bm25s"

    @classmethod
    def from_env(cls) -> "RetrievalConfig":
        value = cls(
            backend=os.getenv("CREDIT_REVIEW_RETRIEVAL_BACKEND", cls.backend).strip().lower(),
            embedding_model=os.getenv("CREDIT_REVIEW_EMBEDDING_MODEL", cls.embedding_model).strip(),
            reranker_model=os.getenv("CREDIT_REVIEW_RERANKER_MODEL", cls.reranker_model).strip(),
            embedding_revision=os.getenv("CREDIT_REVIEW_EMBEDDING_REVISION") or None,
            reranker_revision=os.getenv("CREDIT_REVIEW_RERANKER_REVISION") or None,
            device=os.getenv("CREDIT_REVIEW_RETRIEVAL_DEVICE") or None,
            batch_size=int(os.getenv("CREDIT_REVIEW_RETRIEVAL_BATCH_SIZE", str(cls.batch_size))),
            local_files_only=os.getenv("CREDIT_REVIEW_RETRIEVAL_LOCAL_FILES_ONLY", "0").lower() in {"1", "true", "yes"},
            bm25_backend=os.getenv("CREDIT_REVIEW_BM25_BACKEND", cls.bm25_backend).strip().lower(),
        )
        value.validate()
        return value

    def validate(self) -> None:
        if self.backend not in {"deterministic", "sentence_transformers"}:
            raise ValueError("CREDIT_REVIEW_RETRIEVAL_BACKEND must be deterministic or sentence_transformers")
        if not self.embedding_model or not self.reranker_model:
            raise ValueError("retrieval model names must not be empty")
        if self.batch_size < 1:
            raise ValueError("CREDIT_REVIEW_RETRIEVAL_BATCH_SIZE must be positive")
        if self.bm25_backend != "bm25s":
            raise ValueError("CREDIT_REVIEW_BM25_BACKEND currently supports bm25s")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "embedding_model": self.embedding_model,
            "reranker_model": self.reranker_model,
            "embedding_revision": self.embedding_revision,
            "reranker_revision": self.reranker_revision,
            "device": self.device,
            "batch_size": self.batch_size,
            "local_files_only": self.local_files_only,
            "bm25_backend": self.bm25_backend,
        }
