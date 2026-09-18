"""Framework-neutral one-click knowledge-base build service."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from collections.abc import Callable
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from credit_review.config.models import RetrievalConfig
from credit_review.domain.errors import ConflictError

from .pipeline import KnowledgeBaseBuilder
from .repository import KnowledgeBaseRepository
from .search_service import KnowledgeBaseSearchService


class BuildManager:
    """Run a bounded build and expose a queryable task record.

    The first implementation executes synchronously so the workflow is easy to
    test.  A queue worker can call ``_run`` later without changing the request,
    status, idempotency or publish contract.
    """

    def __init__(
        self,
        repository: KnowledgeBaseRepository,
        builder: KnowledgeBaseBuilder | None = None,
        *,
        retrieval_backend: str | None = None,
        retrieval_config: RetrievalConfig | None = None,
        index_root: Path | str | None = None,
        router_factory: Callable[[list[dict[str, Any]]], Any] | None = None,
        index_builder: Callable[[str, str, Mapping[str, Any]], Mapping[str, Any]] | None = None,
    ) -> None:
        if retrieval_backend is None:
            retrieval_backend = (retrieval_config or RetrievalConfig.from_env()).backend
        if retrieval_config is None:
            retrieval_config = RetrievalConfig(backend=retrieval_backend)
        retrieval_config.validate()
        if retrieval_config.backend != retrieval_backend:
            raise ValueError("retrieval_backend must match retrieval_config.backend")
        self.repository = repository
        self.builder = builder or KnowledgeBaseBuilder()
        self.retrieval_backend = retrieval_backend
        self.retrieval_config = retrieval_config
        self.index_root = index_root or (repository.root / "indexes" if retrieval_backend == "sentence_transformers" else None)
        self.router_factory = router_factory
        if index_builder is not None:
            self.index_builder = index_builder
        elif retrieval_backend == "sentence_transformers":
            from credit_review.infrastructure.index_builder import ProductionIndexBuilder

            self.index_builder = ProductionIndexBuilder(self.index_root, config=retrieval_config)
        else:
            self.index_builder = None
        self._builds: dict[str, dict[str, Any]] = {}
        self._idempotency: dict[tuple[str, str, str], str] = {}
        self._request_fingerprints: dict[str, str] = {}

    def create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        required = ("kb_id", "tenant_id", "requested_by", "idempotency_key", "source")
        missing = [field for field in required if not payload.get(field)]
        if missing:
            raise ValueError(f"missing required fields: {', '.join(missing)}")
        kb_id = str(payload["kb_id"])
        tenant_id = str(payload["tenant_id"])
        idempotency_key = str(payload["idempotency_key"])
        key = (tenant_id, kb_id, idempotency_key)
        request_fingerprint = self._fingerprint(payload)
        if key in self._idempotency:
            existing_id = self._idempotency[key]
            existing = self._builds[existing_id]
            if self._request_fingerprints.get(existing_id) != request_fingerprint:
                raise ConflictError("idempotency key was already used for a different build request")
            return deepcopy(existing)

        build_id = f"B-{uuid4().hex}"
        version = str(payload.get("kb_version") or payload.get("document_version") or "v1")
        record: dict[str, Any] = {
            "build_id": build_id,
            "kb_id": kb_id,
            "tenant_id": tenant_id,
            "requested_by": str(payload["requested_by"]),
            "status": "QUEUED",
            "kb_version": version,
            "retrieval_backend": self.retrieval_backend,
            "retrieval_config": self.retrieval_config.safe_dict(),
            "stages": [],
            "errors": [],
        }
        self._builds[build_id] = record
        self._idempotency[key] = build_id
        self._request_fingerprints[build_id] = request_fingerprint
        self._run(build_id, payload)
        return deepcopy(record)

    def get(self, build_id: str) -> dict[str, Any]:
        try:
            return deepcopy(self._builds[build_id])
        except KeyError as exc:
            raise KeyError(f"unknown build: {build_id}") from exc

    def cancel(self, build_id: str) -> dict[str, Any]:
        record = self._builds[build_id]
        if record["status"] in {"READY", "FAILED", "CANCELLED"}:
            raise ConflictError(f"build cannot be cancelled from {record['status']}")
        record["status"] = "CANCELLED"
        return deepcopy(record)

    def list_versions(self, kb_id: str) -> list[str]:
        return self.repository.list_versions(kb_id)

    def load_active(self, kb_id: str) -> dict[str, Any]:
        return self.repository.load(kb_id)

    def search(self, kb_id: str, query: Mapping[str, Any], *, version: str | None = None, scope: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        service = KnowledgeBaseSearchService(
            self.repository,
            kb_id,
            version=version,
            default_scope=scope,
            retrieval_backend=self.retrieval_backend,
            retrieval_config=self.retrieval_config,
            index_root=self.index_root,
            router_factory=self.router_factory,
        )
        return service.retrieve(query, scope)

    def _run(self, build_id: str, payload: Mapping[str, Any]) -> None:
        record = self._builds[build_id]
        try:
            self._stage(record, "VALIDATING")
            self._stage(record, "PARSING")
            version = record["kb_version"]
            builder = self.builder
            if getattr(builder, "document_version", version) != version:
                builder = KnowledgeBaseBuilder(document_version=version, parser_version=getattr(builder, "parser_version", "mineru-adapter-v1"))
            snapshot = builder.build(
                payload["source"],
                document_id=payload.get("document_id"),
                source_name=payload.get("source_name"),
            )
            self._stage(record, "ENRICHING", {"parent_count": snapshot["manifest"]["parent_count"], "child_count": snapshot["manifest"]["child_count"]})
            self._stage(record, "INDEXING")
            if self.index_builder is not None:
                snapshot["manifest"].update(dict(self.index_builder(record["kb_id"], version, snapshot)))
            self.repository.save_staging(record["kb_id"], version, snapshot)
            self._stage(record, "CHECKING", {"evidence_count": snapshot["manifest"]["evidence_count"]})
            self._stage(record, "PUBLISHING")
            published = self.repository.publish(
                record["kb_id"],
                version,
                expected_active_version=payload.get("expected_active_version"),
            )
            record.update({"status": "READY", "active_version": published["version"], "manifest": snapshot["manifest"]})
        except Exception as exc:
            record["status"] = "FAILED"
            record["errors"].append({"code": type(exc).__name__, "message": str(exc)})

    @staticmethod
    def _stage(record: dict[str, Any], status: str, details: Mapping[str, Any] | None = None) -> None:
        if record["status"] == "CANCELLED":
            raise ConflictError("build was cancelled")
        record["status"] = status
        record["stages"].append({"status": status, "details": dict(details or {})})

    @staticmethod
    def _fingerprint(payload: Mapping[str, Any]) -> str:
        """Create a stable idempotency fingerprint without retaining source data."""

        encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
        return sha256(encoded.encode("utf-8")).hexdigest()
