from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import unittest

from credit_review.observability.trace import ConsoleAgentTrace


class ConsoleAgentTraceTests(unittest.TestCase):
    def test_prints_node_summary_and_route_reason(self) -> None:
        output = StringIO()
        trace = ConsoleAgentTrace()
        with redirect_stdout(output):
            trace({"type": "node_start", "node": "plan_query", "child_id": "F00101", "attempt": 0})
            trace({
                "type": "node_finish",
                "node": "plan_query",
                "child_id": "F00101",
                "attempt": 0,
                "elapsed_ms": 1.25,
                "summary": {"analysis_concept": "solvency"},
            })
            trace({"type": "route", "source": "grade_evidence", "destination": "rewrite_query", "reason": "missing evidence"})

        rendered = output.getvalue()
        self.assertIn("START plan_query child=F00101 attempt=0", rendered)
        self.assertIn('"analysis_concept": "solvency"', rendered)
        self.assertIn("grade_evidence -> rewrite_query | missing evidence", rendered)


if __name__ == "__main__":
    unittest.main()
