"""Small, deterministic numeric checks for common financial claims."""

from __future__ import annotations

import re
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from typing import Any

from credit_review.domain.models import NumericCheck

_NUMBER = r"-?\d+(?:\.\d+)?"
_CHANGE_RE = re.compile(rf"(?P<direction>增长|下降|上升|减少)\s*(?P<value>{_NUMBER})\s*(?P<unit>%|个百分点|个百分[点])")


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal: {value}") from exc


def validate_change(current: Decimal | int | float, previous: Decimal | int | float, claimed_percent: Decimal | int | float, tolerance: Decimal = Decimal("0.01")) -> NumericCheck:
    current_d, previous_d, claimed_d = map(lambda x: Decimal(str(x)), (current, previous, claimed_percent))
    expression = "(current - previous) / abs(previous) * 100"
    if previous_d == 0:
        return NumericCheck("change-zero-base", expression, {"current": current_d, "previous": previous_d}, {"current": "amount", "previous": "amount"}, {}, claimed_d, None, tolerance, None, "previous value is zero")
    observed = (current_d - previous_d) / abs(previous_d) * 100
    passed = abs(observed - claimed_d) <= tolerance
    return NumericCheck("change-check", expression, {"current": current_d, "previous": previous_d}, {"current": "amount", "previous": "amount"}, {}, claimed_d, observed, tolerance, passed, None if passed else "claimed change does not match operands")


class DeterministicNumericValidator:
    """Validates a claim against evidence text without asking an LLM to calculate."""

    def validate(self, child: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        fact = str(child.get("fact", ""))
        claims = list(_CHANGE_RE.finditer(fact))
        if not claims:
            return []
        checks: list[dict[str, Any]] = []
        for index, match in enumerate(claims, 1):
            expected = _decimal(match.group("value"))
            wanted_direction = "下降" if match.group("direction") in {"下降", "减少"} else "增长"
            matching = [item for item in evidence if self._same_metric(fact, str(item.get("content", "")))]
            observed_values = [self._extract_change(str(item.get("content", ""))) for item in matching]
            observed_values = [item for item in observed_values if item is not None]
            observed = observed_values[0] if observed_values else None
            passed = None
            reason = "no comparable external numeric claim"
            if observed is not None:
                observed_direction, observed_value, observed_unit, observed_periods = observed
                claim_periods = set(re.findall(r"20\d{2}", fact))
                period_match = not claim_periods or not observed_periods or bool(claim_periods & observed_periods)
                unit_match = match.group("unit") == observed_unit
                passed = observed_direction == wanted_direction and abs(observed_value - expected) <= Decimal("0.01") and period_match and unit_match
                reason = None if passed else "direction, period, unit or value differs"
            checks.append(asdict(NumericCheck(
                check_id=f"numeric-{child.get('fact_id', 'unknown')}-{index}",
                expression="reported change compared with external change",
                operands={"expected": expected}, units={"change": match.group("unit")}, periods={},
                expected=expected, observed=observed, tolerance=Decimal("0.01"), passed=passed,
                failure_reason=reason,
            )))
        return checks

    @staticmethod
    def _same_metric(fact: str, content: str) -> bool:
        metrics = ("营业收入", "收入", "利润", "毛利率", "资产负债率", "流动比率", "速动比率", "现金流")
        return any(metric in fact and metric in content for metric in metrics)

    @staticmethod
    def _extract_change(content: str) -> tuple[str, Decimal, str, set[str]] | None:
        match = _CHANGE_RE.search(content)
        if not match:
            return None
        direction = "下降" if match.group("direction") in {"下降", "减少"} else "增长"
        return direction, _decimal(match.group("value")), match.group("unit"), set(re.findall(r"20\d{2}", content))
