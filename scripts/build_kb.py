#!/usr/bin/env python3
"""Build a small JSON Evidence index from local text/OCR exports.

This is intentionally provider-free. It establishes the Evidence contract and
can later be replaced by a Chroma/OpenSearch adapter without changing review
inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from credit_review.knowledge_base import KnowledgeBaseBuilder, build_knowledge_base


def _period(text: str) -> str | None:
    match = re.search(r"20\d{2}", text)
    return match.group(0) if match else None


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def build_evidence_index(input_dir: Path, output_file: Path, *, document_version: str = "v1") -> list[dict[str, Any]]:
    files = sorted(path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() in {".txt", ".md"})
    if not files:
        raise FileNotFoundError(f"no .txt/.md source files found in {input_dir}")
    evidence: list[dict[str, Any]] = []
    for file_index, path in enumerate(files, 1):
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            print(f"[建库] 跳过空文件: {path.name}")
            continue
        chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n+", text) if chunk.strip()]
        document_id = f"doc-{path.stem}"
        print(f"[建库] ({file_index}/{len(files)}) {path.name}: {len(chunks)} 个证据片段")
        for chunk_index, chunk in enumerate(chunks, 1):
            is_table = chunk.startswith("[TABLE]") or "表" in chunk[:20]
            content = chunk.replace("[TABLE]", "", 1).strip()
            evidence.append({
                "evidence_id": f"E{len(evidence) + 1:04d}",
                "content": content,
                "source": path.name,
                "page": None,
                "evidence_type": "table" if is_table else "text",
                "document_id": document_id,
                "document_version": document_version,
                "period": _period(chunk),
                "chunk_index": chunk_index,
                "content_hash": _content_hash(content),
            })
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[建库] 完成: {len(evidence)} 个证据片段 → {output_file}")
    return evidence


def build_parent_child_index(input_dir: Path, output_file: Path, *, document_version: str = "v1") -> dict[str, Any]:
    """Build a multi-document Parent–Child snapshot using the MinerU adapter."""

    files = sorted(path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() in {".txt", ".md", ".json"})
    if not files:
        raise FileNotFoundError(f"no supported source files found in {input_dir}")
    builder = KnowledgeBaseBuilder(document_version=document_version)
    documents: list[dict[str, Any]] = []
    for index, path in enumerate(files, 1):
        print(f"[建库] Parent–Child ({index}/{len(files)}) {path.name}")
        documents.append(builder.build(path, document_id=f"doc-{path.stem}", source_name=path.name))
    manifest = {
        "schema_version": "knowledge-base-v1",
        "document_version": document_version,
        "document_count": len(documents),
        "parent_count": sum(item["manifest"]["parent_count"] for item in documents),
        "child_count": sum(item["manifest"]["child_count"] for item in documents),
        "status": "READY",
    }
    snapshot = {"schema_version": "knowledge-base-v1", "documents": documents, "manifest": manifest}
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[建库] Parent–Child 完成: {manifest['child_count']} 个 Child → {output_file}")
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an Evidence or Parent–Child knowledge-base snapshot")
    parser.add_argument("--input-dir", type=Path, default=Path("examples/data/source"))
    parser.add_argument("--output", type=Path, default=Path("examples/data/kb/evidence.json"))
    parser.add_argument("--parent-child-output", type=Path, help="write a MinerU-compatible Parent–Child snapshot")
    parser.add_argument("--mineru-json", type=Path, help="build one snapshot from a MinerU JSON export")
    parser.add_argument("--document-id", help="document ID used with --mineru-json")
    parser.add_argument("--document-version", default="v1")
    args = parser.parse_args()
    if args.mineru_json:
        build_knowledge_base(args.mineru_json, args.parent_child_output or args.output, document_id=args.document_id, document_version=args.document_version)
    elif args.parent_child_output:
        build_parent_child_index(args.input_dir, args.parent_child_output, document_version=args.document_version)
    else:
        build_evidence_index(args.input_dir, args.output, document_version=args.document_version)


if __name__ == "__main__":
    main()
