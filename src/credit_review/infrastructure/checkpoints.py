from __future__ import annotations

from copy import deepcopy
from typing import Any

from credit_review.domain.errors import CheckpointError


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {}

    def save(self, thread_id: str, state: dict[str, Any]) -> None:
        if not thread_id:
            raise CheckpointError("thread_id is required")
        self._states[thread_id] = deepcopy(state)

    def load(self, thread_id: str) -> dict[str, Any]:
        try:
            return deepcopy(self._states[thread_id])
        except KeyError as exc:
            raise CheckpointError(f"checkpoint not found: {thread_id}") from exc

    def delete(self, thread_id: str) -> None:
        self._states.pop(thread_id, None)
