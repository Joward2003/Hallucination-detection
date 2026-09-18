from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from credit_review.graph.builder import run_review
from credit_review.knowledge_base import KnowledgeBaseBuilder, evidence_from_snapshot, parse_mineru_export


class KnowledgeBasePipelineTests(unittest.TestCase):
    def test_mineru_blocks_create_parent_child_and_keep_table_locator(self) -> None:
        payload = {
            "content_list": [
                {"type": "title", "text": "第三节 偿债能力", "text_level": 1, "page_idx": 4},
                {"type": "text", "text": "公司流动性良好。短期债务风险可控。", "page_idx": 5, "bbox": [1, 2, 3, 4]},
                {"type": "table", "table_body": "指标 | 2024\n流动比率 | 1.5", "page_idx": 6, "table_id": "T-1"},
            ]
        }
        snapshot = KnowledgeBaseBuilder(document_version="2024-v1").build(payload, document_id="D1", source_name="report.json")
        self.assertEqual(snapshot["manifest"]["status"], "READY")
        self.assertEqual(snapshot["manifest"]["parent_count"], 3)
        self.assertEqual(snapshot["manifest"]["child_count"], 4)
        table = next(item for item in snapshot["evidence"] if item["evidence_type"] == "table")
        self.assertEqual(table["table_id"], "T-1")
        self.assertEqual(table["page"], 7)
        self.assertIn("current_ratio", table["metric_ids"])
        self.assertTrue(table["structured"])
        child = next(item for item in snapshot["children"] if item["parent_id"] == table["parent_id"])
        self.assertEqual(child["source_locator"]["table_id"], "T-1")
        self.assertTrue(child["source_locator"]["document_id"] == "D1")
        self.assertIn("current_ratio", child["metric_ids"])

    def test_text_fallback_and_json_output_are_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "annual.txt"
            output = Path(directory) / "kb" / "snapshot.json"
            source.write_text("标题\n\n公司收入增长。公司现金流改善。", encoding="utf-8")
            snapshot = KnowledgeBaseBuilder().build(source)
            output.parent.mkdir()
            output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            loaded = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(loaded["manifest"], snapshot["manifest"])
            self.assertEqual(len(parse_mineru_export(source)), 2)
            self.assertTrue(all(item["source_locator"]["document_version"] == "v1" for item in snapshot["children"]))

    def test_snapshot_evidence_runs_through_review_graph(self) -> None:
        snapshot = KnowledgeBaseBuilder(document_version="2024-v1").build(
            {"content_list": [{"type": "table", "text": "甲公司2024年流动比率为1.5。", "page_idx": 2, "table_id": "T-9"}]},
            document_id="D9",
            source_name="annual.json",
        )
        state = run_review("甲公司2024年流动比率为1.5。", evidence=evidence_from_snapshot(snapshot))
        child = state["review_result"]["completed_results"][0]
        self.assertEqual(child["status"], "SUPPORTED")
        self.assertEqual(child["evidence"][0]["document_id"], "D9")
        self.assertEqual(child["evidence"][0]["table_id"], "T-9")


if __name__ == "__main__":
    unittest.main()
