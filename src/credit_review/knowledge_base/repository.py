"""Small file-backed knowledge-base version repository.

The repository is deliberately boring: JSON snapshots are immutable version
artifacts and ``active.json`` is the only mutable pointer.  It is suitable for
local development and tests, while the same publish contract can later be
implemented by object storage plus a metadata database.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from credit_review.domain.errors import CheckpointError, ConflictError


def _safe_component(value: str, field: str) -> str:
    text = str(value).strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text:
        raise ValueError(f"invalid {field}")
    return text


class KnowledgeBaseRepository:
    """Persist immutable KB snapshots and atomically switch the active version."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def save_staging(self, kb_id: str, version: str, snapshot: Mapping[str, Any]) -> Path:
        kb = _safe_component(kb_id, "kb_id")
        ver = _safe_component(version, "version")
        if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("manifest"), Mapping):
            raise ValueError("snapshot manifest is required")
        directory = self.root / kb / "versions"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{ver}.json"
        serialized = json.dumps(dict(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if target.exists():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CheckpointError(f"invalid existing staging snapshot: {kb}/{ver}") from exc
            existing_serialized = json.dumps(existing, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if existing_serialized == serialized:
                return target
            raise ConflictError(f"KB version already contains a different snapshot: {kb}/{ver}")
        temporary = directory / f".{ver}.{uuid4().hex}.tmp"
        temporary.write_text(json.dumps(dict(snapshot), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)
        return target

    def publish(self, kb_id: str, version: str, *, expected_active_version: str | None = None) -> dict[str, Any]:
        kb = _safe_component(kb_id, "kb_id")
        ver = _safe_component(version, "version")
        target = self.root / kb / "versions" / f"{ver}.json"
        if not target.exists():
            raise CheckpointError(f"staging version not found: {kb}/{ver}")
        try:
            staged = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckpointError(f"invalid staging snapshot: {kb}/{ver}") from exc
        if not isinstance(staged, dict) or staged.get("manifest", {}).get("status") != "READY":
            raise ConflictError(f"staging version is not READY: {kb}/{ver}")
        current = self._active_pointer(kb)
        current_version = current.get("version") if current else None
        if expected_active_version is not None and current_version != expected_active_version:
            raise ConflictError(
                f"active KB version changed: expected {expected_active_version!r}, got {current_version!r}"
            )
        pointer = {
            "kb_id": kb,
            "version": ver,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        active_path = self.root / kb / "active.json"
        active_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = active_path.with_name(f".{active_path.name}.{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(pointer, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, active_path)
        return deepcopy(pointer)

    def load(self, kb_id: str, version: str | None = None) -> dict[str, Any]:
        kb = _safe_component(kb_id, "kb_id")
        ver = _safe_component(version, "version") if version is not None else self.active_version(kb)
        path = self.root / kb / "versions" / f"{ver}.json"
        if not path.exists():
            raise CheckpointError(f"KB version not found: {kb}/{ver}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckpointError(f"invalid KB snapshot: {kb}/{ver}") from exc

    def active_version(self, kb_id: str) -> str:
        kb = _safe_component(kb_id, "kb_id")
        pointer = self._active_pointer(kb)
        if not pointer or not pointer.get("version"):
            raise CheckpointError(f"active KB version not found: {kb}")
        return str(pointer["version"])

    def active_pointer(self, kb_id: str) -> dict[str, Any]:
        kb = _safe_component(kb_id, "kb_id")
        pointer = self._active_pointer(kb)
        if pointer is None:
            raise CheckpointError(f"active KB version not found: {kb}")
        return deepcopy(pointer)

    def list_versions(self, kb_id: str) -> list[str]:
        kb = _safe_component(kb_id, "kb_id")
        directory = self.root / kb / "versions"
        if not directory.exists():
            return []
        return sorted(path.stem for path in directory.glob("*.json"))

    def _active_pointer(self, kb_id: str) -> dict[str, Any] | None:
        path = self.root / kb_id / "active.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckpointError(f"invalid active KB pointer: {kb_id}") from exc
        return payload if isinstance(payload, dict) else None
