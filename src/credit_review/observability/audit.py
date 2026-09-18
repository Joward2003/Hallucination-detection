from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    review_id: str
    actor: str
    payload: dict[str, Any]
    occurred_at: str


class InMemoryAuditSink:
    """Append-only sink for tests and local development."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def append(self, event_type: str, review_id: str, actor: str, payload: dict[str, Any]) -> AuditEvent:
        event = AuditEvent(event_type, review_id, actor, dict(payload), datetime.now(timezone.utc).isoformat())
        self._events.append(event)
        return event

    def list(self, review_id: str | None = None) -> list[dict[str, Any]]:
        events = self._events if review_id is None else [item for item in self._events if item.review_id == review_id]
        return [asdict(item) for item in events]
