"""Build-time persistence for the production Dense and BM25S indexes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from credit_review.config.models import RetrievalConfig

from .bm25_service import BM25SService
from .embeddings import SentenceTransformerDenseRetriever, SentenceTransformerEmbedder


class ProductionIndexBuilder:
    """Create both first-stage indexes inside an immutable KB version."""

    def __init__(
        self,
        root: Path | str,
        *,
        config: RetrievalConfig | None = None,
        embedder: Any | None = None,
        bm25_service_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.root = Path(root)
        self.config = config or RetrievalConfig(backend="sentence_transformers")
        self.config.validate()
        if self.config.backend != "sentence_transformers":
            raise ValueError("ProductionIndexBuilder requires backend='sentence_transformers'")
        self.embedder = embedder
        self.bm25_service_factory = bm25_service_factory or BM25SService

    def build(self, kb_id: str, version: str, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        from credit_review.knowledge_base.pipeline import evidence_from_snapshot

        evidence = evidence_from_snapshot(snapshot)
        index_dir = self.root / str(kb_id) / str(version)
        index_dir.mkdir(parents=True, exist_ok=True)
        embedder = self.embedder or SentenceTransformerEmbedder(
            self.config.embedding_model,
            revision=self.config.embedding_revision,
            device=self.config.device,
            batch_size=self.config.batch_size,
            local_files_only=self.config.local_files_only,
        )
        dense_path = index_dir / "dense.json"
        SentenceTransformerDenseRetriever(
            evidence,
            embedder,
            top_k=50,
            index_path=dense_path,
            persist_if_built=True,
        )
        bm25_path = index_dir / "bm25s"
        self.bm25_service_factory(
            evidence,
            top_k=50,
            index_path=bm25_path,
            persist_if_built=True,
        )
        return {
            "dense_index_ref": str(dense_path),
            "bm25_index_ref": str(bm25_path),
            "embedding_profile": self.config.embedding_model,
            "embedding_revision": self.config.embedding_revision,
            "tokenizer_profile": "financial_tokens-v1",
            "reranker_profile": self.config.reranker_model,
            "reranker_revision": self.config.reranker_revision,
        }

    __call__ = build
