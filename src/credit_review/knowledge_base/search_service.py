"""Version-pinned online search over published knowledge-base snapshots."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Mapping

from credit_review.config.models import RetrievalConfig
from credit_review.retrieval.service import RetrievalRouter

from .pipeline import evidence_from_snapshot
from .repository import KnowledgeBaseRepository


class KnowledgeBaseSearchService:
    """Resolve one KB version for a request and delegate to retrieval workers."""

    def __init__(
        self,
        repository: KnowledgeBaseRepository,
        kb_id: str,
        *,
        version: str | None = None,
        default_scope: Mapping[str, Any] | None = None,
        router_factory: Callable[[list[dict[str, Any]]], RetrievalRouter] | None = None,
        retrieval_backend: str | None = None,
        retrieval_config: RetrievalConfig | None = None,
        index_root: Path | str | None = None,
    ) -> None:
        if retrieval_backend is None:
            retrieval_backend = (retrieval_config or RetrievalConfig.from_env()).backend
        if retrieval_config is not None:
            retrieval_config.validate()
            if retrieval_config.backend != retrieval_backend:
                raise ValueError("retrieval_backend must match retrieval_config.backend")
        self.repository = repository
        self.kb_id = kb_id
        self.version = version
        self.default_scope = dict(default_scope or {})
        self.router_factory = router_factory
        self.retrieval_backend = retrieval_backend
        self.retrieval_config = retrieval_config
        self.index_root = Path(index_root) if index_root is not None else None
        self._resolved_version: str | None = version
        self._loaded_version: str | None = None
        self._router: RetrievalRouter | None = None

    def retrieve(self, query: Mapping[str, Any], scope: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        # Resolve active once per service instance.  A review request can make
        # several bounded retrieval rounds and must stay on one KB snapshot.
        resolved_version = self._resolved_version or self.repository.active_version(self.kb_id)
        self._resolved_version = resolved_version
        self._ensure_loaded(resolved_version)
        effective_scope = self.default_scope if scope is None else scope
        hits = self._router.retrieve(query, effective_scope) if self._router is not None else []
        for item in hits:
            item["kb_id"] = self.kb_id
            item["kb_version"] = resolved_version
        return hits

    search = retrieve

    @property
    def resolved_version(self) -> str | None:
        return self._resolved_version

    def _ensure_loaded(self, version: str) -> None:
        if self._loaded_version == version and self._router is not None:
            return
        snapshot = self.repository.load(self.kb_id, version)
        evidence = evidence_from_snapshot(snapshot)
        if self.router_factory is not None:
            self._router = self.router_factory(evidence)
        elif self.retrieval_backend == "sentence_transformers":
            from credit_review.infrastructure.retrieval_stack import create_production_router

            index_dir = self.index_root / self.kb_id / version if self.index_root is not None else None
            self._router = create_production_router(
                evidence,
                config=self.retrieval_config or RetrievalConfig(backend="sentence_transformers"),
                index_dir=index_dir,
                default_scope=self.default_scope,
            )
        elif self.retrieval_backend == "deterministic":
            self._router = RetrievalRouter(evidence, default_scope=self.default_scope)
        else:
            raise ValueError(f"unsupported retrieval backend: {self.retrieval_backend}")
        self._loaded_version = version
