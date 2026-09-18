"""Pure graph routing functions; no I/O is allowed here."""

from typing import Literal, Mapping, Any


def route_after_grading(state: Mapping[str, Any], max_attempts: int = 2) -> Literal["rewrite_query", "verify"]:
    return "rewrite_query" if state.get("evidence_status") == "INSUFFICIENT" and int(state.get("retry_count", 0)) < max_attempts - 1 else "verify"


def route_after_risk(state: Mapping[str, Any]) -> Literal["critic", "human", "finalize"]:
    next_step = (state.get("risk_decision") or {}).get("next_step")
    if next_step == "human":
        return "human"
    if next_step == "critic":
        return "critic"
    return "finalize"


def route_after_compare(state: Mapping[str, Any]) -> Literal["human", "finalize"]:
    initial = state.get("initial_verdict") or {}
    critic = state.get("critic_verdict") or {}
    return "human" if initial.get("status") != critic.get("status") else "finalize"
