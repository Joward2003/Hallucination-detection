"""Sentence-Transformers dense retrieval adapters.

The deterministic hash retriever remains useful for tests, but production
queries should use a real bi-encoder and persist the vectors with the KB
version.  This module keeps model loading lazy so importing the application
does not download a model or require PyTorch.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Protocol, Sequence

from credit_review.retrieval.filters import filter_by_scope
from credit_review.retrieval.service import _bounded_top_k, _candidate_dict


class TextEmbedder(Protocol):
    model_name: str

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class SentenceTransformerEmbedder:
    """Lazy wrapper around ``sentence_transformers.SentenceTransformer``."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        *,
        model: Any | None = None,
        revision: str | None = None,
        device: str | None = None,
        batch_size: int = 32,
        normalize_embeddings: bool = True,
        local_files_only: bool = False,
    ) -> None:
        if not model_name.strip():
            raise ValueError("embedding model name must not be empty")
        if batch_size < 1:
            raise ValueError("embedding batch_size must be positive")
        self.model_name = model_name
        self.revision = revision
        self.batch_size = batch_size
        self.normalize_embeddings = normalize_embeddings
        if model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "SentenceTransformerEmbedder requires the optional 'rag' dependencies; "
                    "install with `pip install -e '.[rag]'`"
                ) from exc
            model_kwargs = {"local_files_only": local_files_only}
            if revision:
                model_kwargs["revision"] = revision
            model = SentenceTransformer(model_name, device=device, model_kwargs=model_kwargs)
        self.model = model

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        values = [str(text or "") for text in texts]
        if not values:
            return []
        encoded = self.model.encode(
            values,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=self.normalize_embeddings,
            show_progress_bar=False,
        )
        if hasattr(encoded, "tolist"):
            encoded = encoded.tolist()
        if encoded and isinstance(encoded[0], (int, float)):
            encoded = [encoded]
        vectors: list[list[float]] = []
        for vector in encoded:
            values_for_vector = [float(item) for item in vector]
            if not values_for_vector or not all(math.isfinite(item) for item in values_for_vector):
                raise ValueError("embedding model returned an invalid vector")
            vectors.append(values_for_vector)
        if len(vectors) != len(values):
            raise ValueError("embedding model returned a vector count mismatch")
        return vectors


class SentenceTransformerDenseRetriever:
    """Dense retriever backed by a real Sentence-Transformers model.

    ``index_path`` is a versioned JSON artifact for the local adapter.  A
    vector database can implement the same ``retrieve`` method and be passed
    to ``HybridSearchService`` without changing the Agentic RAG graph.
    """

    def __init__(
        self,
        candidates: list[dict[str, Any]] | list[Any],
        embedder: TextEmbedder,
        *,
        top_k: int = 50,
        embeddings: list[list[float]] | None = None,
        index_path: Path | str | None = None,
        persist_if_built: bool = False,
    ) -> None:
        self.candidates = [_candidate_dict(item) for item in candidates]
        self.embedder = embedder
        self.model_name = str(getattr(embedder, "model_name", "custom-embedding"))
        self.top_k = _bounded_top_k(top_k, 50)
        self.index_path = Path(index_path) if index_path is not None else None
        if self.index_path is not None and self.index_path.exists():
            self.embeddings = self._load(self.index_path)
        else:
            contents = [str(item.get("content", "")) for item in self.candidates]
            self.embeddings = embeddings if embeddings is not None else embedder.encode(contents)
            self._validate_vectors(self.embeddings)
            if len(self.embeddings) != len(self.candidates):
                raise ValueError("dense index vector count must match candidates")
            if self.index_path is not None and persist_if_built:
                self.save(self.index_path)

    def retrieve(
        self,
        query: str,
        scope: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        query_vector = self.embedder.encode([str(query or "")])[0]
        self._validate_vectors([query_vector])
        allowed = {str(item.get("evidence_id", "")) for item in filter_by_scope(self.candidates, scope)}
        ranked: list[tuple[float, dict[str, Any]]] = []
        for index, candidate in enumerate(self.candidates):
            if str(candidate.get("evidence_id", "")) not in allowed:
                continue
            score = self._cosine(query_vector, self.embeddings[index])
            if score <= 0:
                continue
            item = dict(candidate)
            item.update({"route": "dense", "retrieval_score": round(score, 6), "embedding_model": self.model_name})
            ranked.append((score, item))
        ranked.sort(key=lambda pair: (-pair[0], str(pair[1].get("evidence_id", ""))))
        return [item for _, item in ranked[: _bounded_top_k(top_k, self.top_k)]]

    def save(self, path: Path | str | None = None) -> Path:
        target = Path(path) if path is not None else self.index_path
        if target is None:
            raise ValueError("an index path is required")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "dense-index-v1",
            "model_name": self.model_name,
            "model_revision": getattr(self.embedder, "revision", None),
            "evidence_ids": [str(item.get("evidence_id", "")) for item in self.candidates],
            "vectors": self.embeddings,
        }
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return target

    def _load(self, path: Path) -> list[list[float]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid dense index: {path}") from exc
        if not isinstance(payload, dict):
            raise ValueError("dense index must contain a JSON object")
        if payload.get("schema_version") != "dense-index-v1":
            raise ValueError("unsupported dense index schema")
        expected = [str(item.get("evidence_id", "")) for item in self.candidates]
        if payload.get("evidence_ids") != expected:
            raise ValueError("dense index evidence IDs do not match the KB snapshot")
        vectors = payload.get("vectors")
        if not isinstance(vectors, list) or len(vectors) != len(expected):
            raise ValueError("dense index vector count does not match the KB snapshot")
        self._validate_vectors(vectors)
        if payload.get("model_name") != self.model_name:
            raise ValueError("dense index model does not match the configured embedding model")
        if payload.get("model_revision") != getattr(self.embedder, "revision", None):
            raise ValueError("dense index revision does not match the configured embedding model")
        return [[float(value) for value in vector] for vector in vectors]

    @staticmethod
    def _validate_vectors(vectors: list[list[float]]) -> None:
        dimensions = None
        for vector in vectors:
            if not vector or not all(math.isfinite(float(value)) for value in vector):
                raise ValueError("dense index contains an invalid vector")
            dimensions = dimensions or len(vector)
            if len(vector) != dimensions:
                raise ValueError("dense index vectors have inconsistent dimensions")

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right):
            raise ValueError("query and document embedding dimensions differ")
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm) if left_norm and right_norm else 0.0
