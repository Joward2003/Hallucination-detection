"""Serializable MVP graph state."""

from __future__ import annotations

from typing import Any, TypedDict


class ReviewState(TypedDict, total=False):
    # Task-level state: survives all Child iterations.
    original_input: str
    fact_groups: list[dict[str, Any]]
    flat_children: list[dict[str, Any]]
    company_info: dict[str, Any] | None
    completed_results: list[dict[str, Any]]
    workflow_status: str

    # One-Child working state: reset after finalize_child.
    child_index: int
    current_parent: dict[str, Any]
    current_fact: dict[str, Any]
    retrieval_plan: dict[str, Any] | None
    evidence_requirements: list[dict[str, Any]]
    current_queries: list[dict[str, Any]]
    current_evidence: list[dict[str, Any]]
    retrieval_trace: list[dict[str, Any]]
    evidence_status: str | None
    evidence_observation: dict[str, Any] | None
    missing_needs: list[str]
    retry_count: int
    current_assessments: list[dict[str, Any]]
    verification_result: dict[str, Any] | None
    initial_verdict: dict[str, Any] | None
    critic_verdict: dict[str, Any] | None
    numeric_checks: list[dict[str, Any]]
    rule_hits: list[dict[str, Any]]
    risk_decision: dict[str, Any] | None
    human_task: dict[str, Any] | None

    # Final API-facing graph output.
    review_result: dict[str, Any]
