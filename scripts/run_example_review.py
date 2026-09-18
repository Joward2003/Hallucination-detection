#!/usr/bin/env python3
"""Run the checked-in demonstration report through the review graph."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from credit_review import run_review_with_deepseek
from credit_review.observability.trace import ConsoleAgentTrace


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DeepSeek review example")
    parser.add_argument("--report", type=Path, default=Path("examples/data/report/sample_report.txt"))
    parser.add_argument("--evidence", type=Path, default=Path("examples/data/kb/evidence.json"))
    parser.add_argument("--output", type=Path, default=Path("examples/data/output/sample_review_result.json"))
    parser.add_argument("--trace", action="store_true", help="print the observable Agentic RAG loop to the terminal")
    args = parser.parse_args()
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("[复核] 未检测到 DEEPSEEK_API_KEY，请先 source .env")
    print("[复核] 1/5 读取 AI 报告")
    report = args.report.read_text(encoding="utf-8")
    print(f"[复核]    报告字符数: {len(report)}")
    print("[复核] 2/5 加载 Evidence JSON")
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    print(f"[复核]    证据片段数: {len(evidence)}")
    print("[复核] 3/5 调用 DeepSeek：Parent–Child 抽取、查询规划和事实核验")
    print("[复核] 4/5 本地执行证据过滤、数值校验、规则和风险门控")
    result = run_review_with_deepseek(
        report,
        evidence=evidence,
        source_scope={"allowed_document_ids": sorted({item["document_id"] for item in evidence}), "company_ids": [], "periods": []},
        trace=ConsoleAgentTrace() if args.trace else None,
    )
    print("[复核] 5/5 写入复核结果")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    results = result.get("review_result", {}).get("completed_results", [])
    print(f"[复核] 完成: {len(results)} 个 Child → {args.output}")
    for item in results:
        print(f"[结果] {item['fact_id']} {item['status']} | {item.get('reason', '')}")


if __name__ == "__main__":
    main()
