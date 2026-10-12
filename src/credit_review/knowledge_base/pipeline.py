"""Provider-free ingestion pipeline for MinerU output and local text files.

MinerU is intentionally an input adapter here.  The pipeline stores raw source
blocks and creates searchable Child facts while retaining the Parent context,
table coordinates and document version.  It does not treat generated facts as
independent proof: each Child points back to its source block.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from credit_review.retrieval.service import infer_metric_ids


@dataclass(frozen=True)
class ParsedBlock:
    block_id: str
    block_type: str
    text: str
    page: int | None
    section_path: tuple[str, ...] = ()
    table_id: str | None = None
    bbox: tuple[float, ...] | None = None
    source_index: int = 0
    source_segments: tuple[dict[str, Any], ...] = ()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _page(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value) + 1 if int(value) >= 0 else None
    except (TypeError, ValueError):
        return None


def _bbox(value: Any) -> tuple[float, ...] | None:
    if not isinstance(value, (list, tuple)) or len(value) not in {4, 8}:
        return None
    try:
        return tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None


def _block_text(raw: Mapping[str, Any]) -> str:
    for key in ("text", "content", "text_content", "markdown"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    # MinerU table blocks may expose HTML/markdown in table_body.
    for key in ("table_body", "html", "table_html"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            def captions(name):
                values = raw.get(name) or []
                return [values] if isinstance(values, str) else [str(v) for v in values if isinstance(v, str)]
            return '\n'.join(captions('table_caption') + [value.strip()] + captions('table_footnote'))
    return ""


def parse_mineru_export(source: Path | str | Mapping[str, Any] | list[Any]) -> list[ParsedBlock]:
    """Normalize common MinerU JSON shapes into ordered source blocks."""

    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.suffix.lower() in {".txt", ".md"}:
            return _parse_text(path.read_text(encoding="utf-8"))
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = source

    if isinstance(payload, Mapping):
        raw_blocks = payload.get("blocks") or payload.get("content_list") or payload.get("content") or []
    else:
        raw_blocks = payload
    if not isinstance(raw_blocks, list):
        raise ValueError("MinerU export must contain a list of blocks")

    blocks: list[ParsedBlock] = []
    section_stack: list[str] = []
    for index, raw in enumerate(raw_blocks, 1):
        if isinstance(raw, str):
            raw = {"type": "text", "text": raw}
        if not isinstance(raw, Mapping):
            continue
        text = _block_text(raw)
        if not text:
            continue
        block_type = str(raw.get("type") or raw.get("block_type") or "text").lower()
        if block_type in {"title", "heading", "header"} or (block_type == "text" and int(raw.get("text_level") or 0) > 0):
            level = max(1, int(raw.get("text_level", raw.get("level", 1)) or 1))
            section_stack = section_stack[: level - 1] + [text]
            # Keep headings as context blocks so citations can display them.
            normalized_type = "heading"
        elif "table" in block_type or raw.get("table_body") or raw.get("html"):
            normalized_type = "table"
        else:
            normalized_type = "text"
        table_id = str(raw.get("table_id") or f"T{index:04d}") if normalized_type == "table" else None
        blocks.append(
            ParsedBlock(
                block_id=str(raw.get("id") or f"B{index:04d}"),
                block_type=normalized_type,
                text=text,
                page=_page(raw.get("page", raw.get("page_idx"))),
                section_path=tuple(section_stack),
                table_id=table_id,
                bbox=_bbox(raw.get("bbox") or raw.get("box")),
                source_index=index,
                source_segments=({'block_id': str(raw.get('id') or f'B{index:04d}'), 'page': _page(raw.get('page', raw.get('page_idx'))), 'bbox': list(_bbox(raw.get('bbox') or raw.get('box')) or ()), 'source_index': index, 'text': text, 'source_hash': _hash(text)},),
            )
        )
    if not blocks:
        raise ValueError("MinerU export contains no non-empty text or table blocks")
    # MinerU may split a single sentence across adjacent boxes on a page.
    # Rejoin unfinished text in the same section across adjacent pages; headings and
    # tables remain separate and retain their original locators.
    merged: list[ParsedBlock] = []
    for block in blocks:
        previous = merged[-1] if merged else None
        previous_end = previous.source_segments[-1]['page'] if previous and previous.source_segments else (previous.page if previous else None)
        adjacent = previous_end is not None and block.page is not None and previous_end <= block.page <= previous_end + 1
        if previous and previous.block_type == block.block_type == 'text' and adjacent and previous.section_path == block.section_path and len(previous.text) + len(block.text) <= 6000 and not re.search(r'[。！？!?；;：:]\s*$', previous.text):
            merged[-1] = ParsedBlock(previous.block_id + '+' + block.block_id, 'text', previous.text + '\n' + block.text, previous.page, previous.section_path, bbox=None, source_index=previous.source_index, source_segments=previous.source_segments + block.source_segments)
        else:
            merged.append(block)
    return merged


def _parse_text(text: str) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    for index, value in enumerate((part.strip() for part in re.split(r"\n\s*\n+", text)), 1):
        if not value:
            continue
        is_table = value.startswith("[TABLE]")
        blocks.append(
            ParsedBlock(
                block_id=f"B{index:04d}",
                block_type="table" if is_table else "text",
                text=value.replace("[TABLE]", "", 1).strip(),
                page=None,
                table_id=f"T{index:04d}" if is_table else None,
                source_index=index,
            )
        )
    if not blocks:
        raise ValueError("source text contains no non-empty blocks")
    return blocks


def _atomic_facts(text: str) -> list[str]:
    values = [part.strip() for part in re.split(r"(?<=[。！？!?])\s*", text) if part.strip()]
    return values or [text.strip()]


class KnowledgeBaseBuilder:
    """Build a serializable Parent–Child knowledge-base snapshot."""

    def __init__(self, *, document_version: str = "v1", parser_version: str = "mineru-adapter-v1") -> None:
        self.document_version = document_version
        self.parser_version = parser_version

    def build(
        self,
        source: Path | str | Mapping[str, Any] | list[Any],
        *,
        document_id: str | None = None,
        source_name: str | None = None,
    ) -> dict[str, Any]:
        blocks = parse_mineru_export(source)
        if isinstance(source, (str, Path)):
            path = Path(source)
            source_name = source_name or path.name
            document_id = document_id or f"doc-{path.stem}"
        else:
            source_name = source_name or "mineru-export.json"
            document_id = document_id or f"doc-{_hash(source_name)[:12]}"

        parents: list[dict[str, Any]] = []
        children: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        for parent_index, block in enumerate(blocks, 1):
            parent_id = f"P{parent_index:04d}"
            locator = {
                "document_id": document_id,
                "document_version": self.document_version,
                "source": source_name,
                "page": block.page,
                "page_end": block.source_segments[-1]['page'] if block.source_segments else block.page,
                "source_segments": list(block.source_segments),
                "section": " / ".join(block.section_path) or None,
                "table_id": block.table_id,
                "bbox": list(block.bbox) if block.bbox else None,
                "block_id": block.block_id,
            }
            parent = {
                "parent_id": parent_id,
                "parent_text": block.text,
                "parent_type": block.block_type,
                "section_path": list(block.section_path),
                "source_locator": locator,
                "source_hash": _hash(block.text),
            }
            parents.append(parent)
            for child_index, fact in enumerate(_atomic_facts(block.text), 1):
                child_id = f"{parent_id}-C{child_index:02d}"
                child_metrics = sorted(infer_metric_ids({"content": fact}))
                child = {
                    "child_id": child_id,
                    "fact_id": child_id,
                    "parent_id": parent_id,
                    "fact_text": fact,
                    "fact": fact,
                    "is_derived": fact != block.text,
                    "source_locator": locator,
                    "source_hash": _hash(fact),
                    "metric_ids": child_metrics,
                }
                children.append(child)
            metric_ids = sorted(infer_metric_ids({"content": block.text}))
            evidence.append(
                {
                    "evidence_id": f"E{parent_index:04d}",
                    "content": block.text,
                    "source": source_name,
                    "page": block.page,
                    "evidence_type": "table" if block.block_type == "table" else "text",
                    "document_id": document_id,
                    "document_version": self.document_version,
                    "section": " / ".join(block.section_path) or None,
                    "table_id": block.table_id,
                    "content_hash": _hash(block.text),
                    "parent_id": parent_id,
                    "chunk_index": parent_index,
                    "metric_ids": metric_ids,
                    "structured": bool(metric_ids and block.block_type == "table"),
                }
            )

        return {
            "schema_version": "knowledge-base-v1",
            "document_id": document_id,
            "document_version": self.document_version,
            "parser_version": self.parser_version,
            "source": source_name,
            "parents": parents,
            "children": children,
            "evidence": evidence,
            "manifest": {
                "document_id": document_id,
                "document_version": self.document_version,
                "parser_version": self.parser_version,
                "parent_count": len(parents),
                "child_count": len(children),
                "evidence_count": len(evidence),
                "chunk_manifest_hash": _hash(json.dumps(children, ensure_ascii=False, sort_keys=True)),
                "status": "READY",
            },
        }


def build_knowledge_base(
    source: Path | str | Mapping[str, Any] | list[Any],
    output: Path | str | None = None,
    *,
    document_id: str | None = None,
    document_version: str = "v1",
) -> dict[str, Any]:
    snapshot = KnowledgeBaseBuilder(document_version=document_version).build(source, document_id=document_id)
    if output is not None:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot


def evidence_from_snapshot(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten a document or multi-document KB snapshot for the review port."""

    if not isinstance(snapshot, Mapping):
        raise ValueError("knowledge-base snapshot must be a mapping")
    if isinstance(snapshot.get("evidence"), list):
        return [dict(item) for item in snapshot["evidence"] if isinstance(item, Mapping)]
    documents = snapshot.get("documents")
    if isinstance(documents, list):
        evidence: list[dict[str, Any]] = []
        for document in documents:
            if isinstance(document, Mapping) and isinstance(document.get("evidence"), list):
                evidence.extend(dict(item) for item in document["evidence"] if isinstance(item, Mapping))
        return evidence
    raise ValueError("knowledge-base snapshot contains no evidence list")
