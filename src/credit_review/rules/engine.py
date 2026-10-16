"""Versioned, deterministic rule execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from credit_review.domain.models import RuleHit


@dataclass(frozen=True)
class Rule:
    rule_id: str
    version: str
    issue_type: str
    severity: str
    predicate: Callable[[dict[str, Any]], bool]
    explanation: str
    required_human_review: bool = False


class RuleEngine:
    def __init__(self, rules: list[Rule] | None = None) -> None:
        self.rules = list(rules or [])

    def register(self, rule: Rule) -> None:
        if any(existing.rule_id == rule.rule_id and existing.version == rule.version for existing in self.rules):
            raise ValueError(f"duplicate rule: {rule.rule_id}@{rule.version}")
        self.rules.append(rule)

    def evaluate(self, context: dict[str, Any], rule_set_version: str = "default") -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        for rule in self.rules:
            triggered = bool(rule.predicate(context))
            if triggered:
                hits.append({
                    "rule_id": rule.rule_id, "rule_version": rule.version,
                    "issue_type": rule.issue_type, "severity": rule.severity,
                    "triggered": True, "facts": {}, "explanation": rule.explanation,
                    "required_human_review": rule.required_human_review,
                })
        return hits


def default_rules() -> list[Rule]:
    return [
        Rule("numeric-check-failed", "2", "fact_mismatch", "high", lambda c: any(item.get("passed") is False for item in c.get("numeric_checks", [])), "确定性数值校验未通过。"),
        Rule("counter-evidence", "2", "evidence_conflict", "high", lambda c: any(item.get("relation") == "CONTRADICTS" for item in c.get("assessments", [])), "存在与报告结论方向相反的外部证据。"),
        Rule("critical-child-human", "2", "manual_review", "critical", lambda c: c.get("risk_level") == "critical", "关键风险 Child 必须人工复核。", True),
    ]
