"""Read-only, bounded PDF page rasterization for browsers without PDF plugins."""
from __future__ import annotations

import re
from pathlib import Path
from threading import Lock

_render_lock = Lock()


def highlight_terms(text: str) -> list[str]:
    terms = []
    for line in text[:2000].splitlines():
        line = line.strip()
        if len(line) >= 2:
            terms.append(line)
        # OCR/table extraction sometimes merges cells. Search each literal
        # number as well; never reconstruct or infer missing financial values.
        for number in re.findall(r'[+\-]?\d[\d,，\s]*\.\d{1,4}(?:%|％)?', line):
            terms.append(re.sub(r'\s+', '', number).replace('，', ','))
    return list(dict.fromkeys(terms))[:40]


def render_page(path: Path, number: int, highlight: str = '') -> tuple[bytes, int]:
    import pymupdf

    with _render_lock, pymupdf.open(path) as document:
        if not 1 <= number <= len(document):
            raise IndexError('PDF 页码超出范围。')
        if document.needs_pass:
            raise ValueError('此 PDF 已加密，无法直接生成预览。')
        page = document[number - 1]
        if page.rect.width <= 0 or page.rect.height <= 0:
            raise ValueError('PDF 页面尺寸无效。')
        matches, seen = [], set()
        for term in highlight_terms(highlight):
            for quad in page.search_for(term, quads=True):
                key = tuple(round(value, 2) for value in quad.rect)
                if key not in seen:
                    seen.add(key)
                    matches.append(quad)
                if len(matches) >= 80:
                    break
            if len(matches) >= 80:
                break
        if matches:
            annotation = page.add_highlight_annot(matches)
            annotation.set_colors(stroke=(1, .83, .32))
            annotation.set_opacity(.45)
            annotation.update()
            page = document.reload_page(page)
        scale = min(2, 1400 / page.rect.width, 2200 / page.rect.height)
        image = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        # The temporary document is never saved; original PDFs and signatures
        # remain unchanged. Matching uses only actual text on this page.
        return image.tobytes('png'), len(matches)
