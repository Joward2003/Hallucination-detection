from __future__ import annotations

from typing import Any


class RiskPolicy:
    def __init__(self, *, critic_on_low_confidence: bool = True, critic_on_counter_evidence: bool = True, critic_on_high_risk_rule: bool = True, human_on_critic_conflict: bool = True, mandatory_human_levels: tuple[str, ...] = ("critical",)) -> None:
        self.critic_on_low_confidence = critic_on_low_confidence
        self.critic_on_counter_evidence = critic_on_counter_evidence
        self.critic_on_high_risk_rule = critic_on_high_risk_rule
        self.human_on_critic_conflict = human_on_critic_conflict
        self.mandatory_human_levels = mandatory_human_levels

    def decide(self, *, child: dict[str, Any], initial_verdict: dict[str, Any], rule_hits: list[dict[str, Any]], has_counter_evidence: bool, critic_verdict: dict[str, Any] | None = None) -> dict[str, Any]:
        level = str(child.get("importance", child.get("risk_level", "low"))).lower()
        reasons: list[str] = []
        if level in self.mandatory_human_levels:
            return {"next_step": "human", "risk_level": level, "reason_codes": ["mandatory_human"]}
        if critic_verdict is not None and critic_verdict.get("status") != initial_verdict.get("status") and self.human_on_critic_conflict:
            return {"next_step": "human", "risk_level": level, "reason_codes": ["critic_conflict"]}
        if has_counter_evidence and self.critic_on_counter_evidence:
            reasons.append("counter_evidence")
        if initial_verdict.get("confidence", initial_verdict.get("confidence_band")) == "low" and self.critic_on_low_confidence:
            reasons.append("low_confidence")
        if self.critic_on_high_risk_rule and any(str(hit.get("severity", "")).lower() in {"high", "critical"} for hit in rule_hits):
            reasons.append("high_risk_rule")
        if reasons:
            return {"next_step": "critic", "risk_level": level, "reason_codes": reasons}
        return {"next_step": "finalize", "risk_level": level, "reason_codes": []}
