"""Cross-Encoder reranker adapters for the second retrieval stage."""

from __future__ import annotations

import math
from typing import Any, Sequence

from credit_review.retrieval.service import _bounded_top_k


class SentenceTransformerCrossEncoder:
    """Run a real Sentence-Transformers CrossEncoder over query/evidence pairs."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        *,
        model: Any | None = None,
        revision: str | None = None,
        device: str | None = None,
        batch_size: int = 16,
        max_length: int = 1024,
        local_files_only: bool = False,
        normalize_scores: bool = True,
    ) -> None:
        if not model_name.strip():
            raise ValueError("reranker model name must not be empty")
        if batch_size < 1 or max_length < 1:
            raise ValueError("reranker batch_size and max_length must be positive")
        self.model_name = model_name
        self.revision = revision
        self.batch_size = batch_size
        self.max_length = max_length
        self.normalize_scores = normalize_scores
        if model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "SentenceTransformerCrossEncoder requires the optional 'rag' dependencies; "
                    "install with `pip install -e '.[rag]'`"
                ) from exc
            model_kwargs = {"local_files_only": local_files_only}
            if revision:
                model_kwargs["revision"] = revision
            model = CrossEncoder(model_name, device=device, max_length=max_length, model_kwargs=model_kwargs)
        self.model = model

    def rank(self, query: str, candidates: list[dict[str, Any]], top_n: int = 12) -> list[dict[str, Any]]:
        bounded = _bounded_top_k(top_n, 12)
        if not candidates:
            return []
        pairs = [(str(query or ""), str(item.get("rerank_text") or item.get("content", ""))) for item in candidates]
        scores = self.model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)
        if hasattr(scores, "tolist"):
            scores = scores.tolist()
        if not isinstance(scores, Sequence) or isinstance(scores, (str, bytes)):
            scores = [scores]
        if len(scores) != len(candidates):
            raise ValueError("cross-encoder score count must match candidates")
        ranked: list[tuple[float, dict[str, Any]]] = []
        for candidate, raw_score in zip(candidates, scores):
            if isinstance(raw_score, Sequence) and not isinstance(raw_score, (str, bytes)):
                raw_score = raw_score[0]
            score = float(raw_score)
            if not math.isfinite(score):
                raise ValueError("cross-encoder returned a non-finite score")
            display_score = self._sigmoid(score) if self.normalize_scores else score
            item = dict(candidate)
            item.update({"rerank_score": round(display_score, 6), "score": round(display_score, 6), "reranker_model": self.model_name})
            ranked.append((display_score, item))
        ranked.sort(key=lambda pair: (-pair[0], -float(pair[1].get("rrf_score", 0.0)), str(pair[1].get("evidence_id", ""))))
        return [item for _, item in ranked[:bounded]]

    @staticmethod
    def _sigmoid(value: float) -> float:
        if value >= 0:
            z = math.exp(-value)
            return 1.0 / (1.0 + z)
        z = math.exp(value)
        return z / (1.0 + z)
