from __future__ import annotations

import re
from typing import Any


class EvidencePlanner:
    def plan(self, child: dict[str, Any], parent: dict[str, Any], rule_hints: list[str] | None = None) -> list[dict[str, Any]]:
        fact = child["fact"]
        kind = "table" if re.search(r"收入|利润|毛利率|比例|金额|同比", fact) else "text"
        need_id = f"N-{child['fact_id']}"
        needs = [{"need_id": need_id, "description": f"核实：{fact}", "evidence_type": kind, "polarity": "support", "required_metrics": [], "required_periods": re.findall(r"20\d{2}", fact)}]
        # A counter search is explicit, never inferred from a missing result.
        if rule_hints and "counter" in rule_hints:
            needs.append({"need_id": f"{need_id}-counter", "description": f"寻找反向证据：{fact}", "evidence_type": kind, "polarity": "counter", "required_metrics": [], "required_periods": re.findall(r"20\d{2}", fact)})
        return needs

    def queries(self, child: dict[str, Any], parent: dict[str, Any], company: dict[str, Any] | None = None, attempt: int = 0) -> list[dict[str, Any]]:
        return [{"query_id": f"Q-{child['fact_id']}-{attempt}", "fact_id": child["fact_id"], "need_id": f"N-{child['fact_id']}", "query_text": child["fact"] if attempt == 0 else f"{child['fact']}；原始语境：{parent['parent_text']}", "retrieval_type": "table" if re.search(r"收入|利润|毛利率|比例|金额|同比", child["fact"]) else "text", "attempt": attempt, "filters": {"company": company or {}}}]
