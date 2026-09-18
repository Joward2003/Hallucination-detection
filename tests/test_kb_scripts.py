from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scripts.build_kb import build_evidence_index, build_parent_child_index
from credit_review.verification.citation import citation_is_traceable


class KnowledgeBaseScriptTests(unittest.TestCase):
    def test_build_script_writes_traceable_evidence_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "report.txt").write_text("第一段 2024年收入增长。\n\n[TABLE] 表1：资产负债率为52%。", encoding="utf-8")
            output = root / "kb" / "evidence.json"
            evidence = build_evidence_index(source, output)
            self.assertEqual(len(evidence), 2)
            self.assertEqual(evidence[1]["evidence_type"], "table")
            self.assertEqual(evidence[0]["document_id"], "doc-report")
            self.assertTrue(evidence[0]["content_hash"])
            self.assertTrue(citation_is_traceable(evidence[0]))
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), evidence)

    def test_build_script_can_write_parent_child_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "report.txt").write_text("第三节 偿债能力\n\n公司流动性良好。\n\n[TABLE] 流动比率为1.5。", encoding="utf-8")
            output = root / "kb" / "parent_child.json"
            snapshot = build_parent_child_index(source, output, document_version="v2")
            self.assertEqual(snapshot["manifest"]["status"], "READY")
            self.assertEqual(snapshot["manifest"]["document_count"], 1)
            self.assertGreaterEqual(snapshot["manifest"]["child_count"], 3)
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["manifest"], snapshot["manifest"])
            self.assertEqual(saved["documents"][0]["document_version"], "v2")


if __name__ == "__main__":
    unittest.main()
