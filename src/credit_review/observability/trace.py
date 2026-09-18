"""Human-readable, opt-in traces for the Agentic RAG workflow.

The trace reports observable inputs, decisions, tool parameters and outputs.
It intentionally does not capture or emit private model chain-of-thought.
"""

from __future__ import annotations

import json
from typing import Any, Mapping


class ConsoleAgentTrace:
    """Print structured Agent-loop events to the terminal."""

    def __call__(self, event: Mapping[str, Any]) -> None:
        event_type = event.get("type")
        node = event.get("node", "")
        child_id = event.get("child_id")
        attempt = event.get("attempt")
        context = "".join(
            part for part in (
                f" child={child_id}" if child_id else "",
                f" attempt={attempt}" if attempt is not None else "",
            )
        )

        if event_type == "node_start":
            print(f"\n[Agent Loop] START {node}{context}", flush=True)
            return
        if event_type == "node_finish":
            status = event.get("workflow_status")
            elapsed = event.get("elapsed_ms")
            suffix = f" status={status}" if status else ""
            if elapsed is not None:
                suffix += f" elapsed={elapsed:.1f}ms"
            print(f"[Agent Loop] DONE  {node}{suffix}", flush=True)
            summary = event.get("summary")
            if summary:
                print(json.dumps(summary, ensure_ascii=False, indent=2, default=str), flush=True)
            return
        if event_type == "route":
            reason = event.get("reason")
            suffix = f" | {reason}" if reason else ""
            print(f"[Agent Loop] ROUTE {event.get('source')} -> {event.get('destination')}{suffix}", flush=True)
            return
        print(json.dumps(dict(event), ensure_ascii=False, indent=2, default=str), flush=True)
