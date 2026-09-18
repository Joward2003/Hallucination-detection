from __future__ import annotations

from .engine import Rule, RuleEngine


class RuleRegistry:
    def __init__(self) -> None:
        self._sets: dict[str, RuleEngine] = {}

    def publish(self, version: str, rules: list[Rule]) -> None:
        if not version or version in self._sets:
            raise ValueError("rule version must be non-empty and unique")
        self._sets[version] = RuleEngine(rules)

    def get(self, version: str) -> RuleEngine:
        try:
            return self._sets[version]
        except KeyError as exc:
            raise KeyError(f"unknown rule set: {version}") from exc
