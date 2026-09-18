"""Persistent BM25S lexical retrieval adapter.

BM25S stores an eagerly scored sparse index and supports disk/memory-mapped
loading.  The adapter adds the financial tokenizer, scope filtering and the
project's evidence metadata contract around that library.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from credit_review.retrieval.filters import filter_by_scope
from credit_review.retrieval.service import _bounded_top_k, _candidate_dict, financial_tokens


class BM25SService:
    """Build or load a real BM25S index for one immutable KB version."""

    def __init__(
        self,
        candidates: list[Mapping[str, Any]] | list[Any],
        *,
        top_k: int = 50,
        index: Any | None = None,
        tokenizer: Any | None = None,
        index_path: Path | str | None = None,
        persist_if_built: bool = False,
        mmap: bool = False,
    ) -> None:
        self.candidates = [_candidate_dict(item) for item in candidates]
        self.top_k = _bounded_top_k(top_k, 50)
        self.index_path = Path(index_path) if index_path is not None else None
        self._bm25s = None if index is not None and tokenizer is not None and self.index_path is None else self._load_library()
        self.tokenizer = tokenizer or self._new_tokenizer()
        if self.index_path is not None and self.index_path.exists():
            self._index = self._load_index(self.index_path, mmap=mmap)
        else:
            self._index = index or self._new_index()
            corpus = [self._token_text(item.get("content", "")) for item in self.candidates]
            tokenized = self.tokenizer.tokenize(corpus)
            self._index.index(tokenized)
            if self.index_path is not None and persist_if_built:
                self.save(self.index_path)

    def retrieve(
        self,
        query: str,
        scope: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        requested = _bounded_top_k(top_k, self.top_k)
        allowed_ids = {str(item.get("evidence_id", "")) for item in filter_by_scope(self.candidates, scope)}
        # Over-retrieve before authorization filtering so a restrictive scope
        # does not consume the whole result window.  The cap remains bounded.
        fetch_k = min(len(self.candidates), max(requested, min(1000, requested * 4)))
        if not fetch_k:
            return []
        query_tokens = self.tokenizer.tokenize([self._token_text(query)], update_vocab=False)
        raw_results, raw_scores = self._index.retrieve(query_tokens, k=fetch_k)
        indices = self._first_row(raw_results)
        scores = self._first_row(raw_scores)
        ranked: list[tuple[float, dict[str, Any]]] = []
        seen: set[str] = set()
        for raw_index, raw_score in zip(indices, scores):
            index = self._resolve_index(raw_index)
            if index is None or index >= len(self.candidates):
                continue
            candidate = self.candidates[index]
            evidence_id = str(candidate.get("evidence_id", ""))
            if evidence_id in seen or evidence_id not in allowed_ids:
                continue
            seen.add(evidence_id)
            score = float(raw_score)
            item = dict(candidate)
            item.update({"route": "bm25", "retrieval_score": round(score, 6), "bm25_score": round(score, 6)})
            ranked.append((score, item))
            if len(ranked) >= requested:
                break
        ranked.sort(key=lambda pair: (-pair[0], str(pair[1].get("evidence_id", ""))))
        return [item for _, item in ranked[:requested]]

    def save(self, path: Path | str | None = None) -> Path:
        target = Path(path) if path is not None else self.index_path
        if target is None:
            raise ValueError("an index path is required")
        target.mkdir(parents=True, exist_ok=True)
        self._index.save(str(target))
        self.tokenizer.save_vocab(save_dir=str(target))
        (target / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "bm25s-index-v1",
                    "evidence_ids": [str(item.get("evidence_id", "")) for item in self.candidates],
                    "tokenizer": "financial_tokens-v1",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return target

    @staticmethod
    def _token_text(value: Any) -> str:
        return " ".join(financial_tokens(str(value or "")))

    def _load_index(self, path: Path, *, mmap: bool) -> Any:
        manifest_path = path / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid BM25S manifest: {path}") from exc
        expected = [str(item.get("evidence_id", "")) for item in self.candidates]
        if manifest.get("schema_version") != "bm25s-index-v1" or manifest.get("evidence_ids") != expected:
            raise ValueError("BM25S index evidence IDs do not match the KB snapshot")
        self.tokenizer.load_vocab(save_dir=str(path))
        return self._bm25s.BM25.load(str(path), mmap=mmap)

    def _load_library(self) -> Any:
        try:
            import bm25s
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "BM25SService requires the optional 'rag' dependencies; install with `pip install -e '.[rag]'`"
            ) from exc
        return bm25s

    def _new_tokenizer(self) -> Any:
        from bm25s.tokenization import Tokenizer

        return Tokenizer(splitter=lambda value: financial_tokens(value))

    def _new_index(self) -> Any:
        return self._bm25s.BM25(method="lucene", k1=1.5, b=0.75)

    @staticmethod
    def _first_row(value: Any) -> list[Any]:
        if hasattr(value, "tolist"):
            value = value.tolist()
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            if value and isinstance(value[0], Sequence) and not isinstance(value[0], (str, bytes)):
                return list(value[0])
            return list(value)
        return [value]

    def _resolve_index(self, value: Any) -> int | None:
        if isinstance(value, Mapping):
            evidence_id = str(value.get("evidence_id", ""))
            return next((index for index, item in enumerate(self.candidates) if str(item.get("evidence_id", "")) == evidence_id), None)
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
