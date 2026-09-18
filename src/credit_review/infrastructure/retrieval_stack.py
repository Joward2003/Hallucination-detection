"""Factories that wire real retrieval adapters into the existing router."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from credit_review.config.models import RetrievalConfig
from credit_review.retrieval.service import HybridSearchService, RetrievalRouter

from .bm25_service import BM25SService
from .embeddings import SentenceTransformerDenseRetriever, SentenceTransformerEmbedder
from .rerankers import SentenceTransformerCrossEncoder


def create_production_hybrid_search(
    candidates: list[Mapping[str, Any]],
    *,
    config: RetrievalConfig | None = None,
    index_dir: Path | str | None = None,
    default_scope: Mapping[str, Any] | None = None,
    embedder: Any | None = None,
    dense_retriever: Any | None = None,
    lexical_retriever: Any | None = None,
    reranker: Any | None = None,
) -> HybridSearchService:
    """Create a Dense + BM25S + CrossEncoder production retrieval stack.

    Dependency injection is intentional: tests can supply small fake models,
    while a deployment uses the defaults backed by Sentence Transformers and
    BM25S.  ``index_dir`` should point inside the immutable KB version.
    """

    config = config or RetrievalConfig(backend="sentence_transformers")
    config.validate()
    if config.backend != "sentence_transformers":
        raise ValueError("production retrieval factory requires backend='sentence_transformers'")
    dense = dense_retriever
    lexical = lexical_retriever
    cross = reranker
    if dense is None:
        actual_embedder = embedder or SentenceTransformerEmbedder(
            config.embedding_model,
            revision=config.embedding_revision,
            device=config.device,
            batch_size=config.batch_size,
            local_files_only=config.local_files_only,
        )
        dense_path = Path(index_dir) / "dense.json" if index_dir is not None else None
        dense = SentenceTransformerDenseRetriever(
            candidates,
            actual_embedder,
            top_k=50,
            index_path=dense_path,
            persist_if_built=dense_path is not None,
        )
    if lexical is None:
        bm25_path = Path(index_dir) / "bm25s" if index_dir is not None else None
        lexical = BM25SService(
            candidates,
            top_k=50,
            index_path=bm25_path,
            persist_if_built=bm25_path is not None,
        )
    if cross is None:
        cross = SentenceTransformerCrossEncoder(
            config.reranker_model,
            revision=config.reranker_revision,
            device=config.device,
            batch_size=config.batch_size,
            local_files_only=config.local_files_only,
        )
    return HybridSearchService(
        candidates,
        dense_top_k=50,
        bm25_top_k=50,
        candidate_top_k=60,
        rerank_top_n=12,
        default_scope=default_scope,
        dense_retriever=dense,
        lexical_retriever=lexical,
        reranker=cross,
    )


def create_production_router(
    candidates: list[Mapping[str, Any]],
    *,
    config: RetrievalConfig | None = None,
    index_dir: Path | str | None = None,
    default_scope: Mapping[str, Any] | None = None,
) -> RetrievalRouter:
    """Create the full router while keeping table/structured workers local."""

    return RetrievalRouter(
        candidates,
        text_search=create_production_hybrid_search(
            candidates,
            config=config,
            index_dir=index_dir,
            default_scope=default_scope,
        ),
        default_scope=default_scope,
    )
