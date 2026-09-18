"""Framework-neutral application service used by HTTP adapters and tests."""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4
from typing import Any

from credit_review.domain.errors import ConflictError
from credit_review.graph.builder import resume_review, run_review

from .schemas import ReviewRequest


class ReviewManager:
    def __init__(self, runner=run_review) -> None:
        self._reviews: dict[str, dict[str, Any]] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._runner = runner

    def create(self, payload: ReviewRequest | dict[str, Any]) -> dict[str, Any]:
        request = payload if isinstance(payload, ReviewRequest) else ReviewRequest.from_dict(payload)
        key = (request.tenant_id, request.idempotency_key)
        if key in self._idempotency:
            return deepcopy(self._reviews[self._idempotency[key]])
        review_id = f"R-{uuid4().hex}"
        state = self._runner(request.report_text, evidence=request.evidence, companies=request.companies, source_scope=request.source_scope)
        record = {"review_id": review_id, "tenant_id": request.tenant_id, "project_id": request.project_id, "requested_by": request.requested_by, "report_id": request.report_id, "status": state.get("workflow_status"), "state": state}
        self._reviews[review_id] = record
        self._idempotency[key] = review_id
        return deepcopy(record)

    def get(self, review_id: str) -> dict[str, Any]:
        try:
            return deepcopy(self._reviews[review_id])
        except KeyError as exc:
            raise KeyError(f"unknown review: {review_id}") from exc

    def cancel(self, review_id: str) -> dict[str, Any]:
        record = self._reviews[review_id]
        if record["status"] == "COMPLETED":
            raise ConflictError("completed review cannot be cancelled")
        record["status"] = "CANCELLED"
        record["state"]["workflow_status"] = "CANCELLED"
        return deepcopy(record)

    def human_tasks(self) -> list[dict[str, Any]]:
        return [
            deepcopy(record["state"]["human_task"]) | {"review_id": record["review_id"]}
            for record in self._reviews.values()
            if (record["state"].get("human_task") or {}).get("status") == "PENDING"
        ]

    def submit_human_decision(self, review_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        record = self._reviews[review_id]
        state = record["state"]
        try:
            state = resume_review(state, decision)
        except ValueError as exc:
            raise ConflictError(str(exc)) from exc
        record["state"] = state
        record["status"] = state["workflow_status"]
        return deepcopy(record)
