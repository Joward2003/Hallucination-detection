"""Read-only source page previews and literal evidence highlighting."""
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from credit_review.workbench.app import create_workbench_app
from credit_review.workbench.pdf_preview import render_page

pymupdf = pytest.importorskip('pymupdf')


@pytest.fixture
def original_pdf(tmp_path):
    path = tmp_path / 'source.pdf'
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((72, 90), 'Revenue 98,660,353.71')
        document.new_page().insert_text((72, 90), 'A different page')
        document.save(path)
    return path


def test_preview_highlights_real_matches_without_modifying_source(original_pdf):
    before = sha256(original_pdf.read_bytes()).hexdigest()
    plain, zero = render_page(original_pdf, 1)
    marked, count = render_page(original_pdf, 1, '98,660,353.71')
    absent, absent_count = render_page(original_pdf, 1, '99,999,999.99')
    assert plain.startswith(b'\x89PNG\r\n\x1a\n')
    assert count == 1 and zero == absent_count == 0
    assert marked != plain and absent == plain
    assert sha256(original_pdf.read_bytes()).hexdigest() == before
    with pymupdf.open(original_pdf) as document:
        assert list(document[0].annots() or []) == []


def test_preview_matches_only_the_requested_page(original_pdf):
    _, count = render_page(original_pdf, 2, '98,660,353.71')
    assert count == 0
    for page in (0, 3):
        with pytest.raises(IndexError):
            render_page(original_pdf, page)


def test_page_preview_api_validates_source_page_and_query(tmp_path, original_pdf):
    app = create_workbench_app(tmp_path / 'data', backend='lexical')
    original = original_pdf.read_bytes()
    with TestClient(app) as client:
        doc = client.post('/v1/documents', files={'file': ('report.pdf', original, 'application/pdf')}).json()
        path = '/v1/documents/' + doc['document_id']
        response = client.get(path + '/pages/1.png', params={'highlight': '98,660,353.71'})
        assert response.status_code == 200
        assert response.headers['content-type'] == 'image/png'
        assert response.headers['x-source-page'] == '1'
        assert response.headers['x-evidence-highlights'] == '1'
        assert client.get(path + '/original').content == original
        assert client.get(path + '/pages/3.png').status_code == 404
        assert client.get(path + '/pages/1.png', params={'highlight': 'x' * 2001}).status_code == 422
        assert client.get(path + '/pages/1.png', headers={'Origin': 'https://outside.example'}).status_code == 403
        text = client.post('/v1/documents', files={'file': ('source.txt', b'plain source')}).json()
        assert client.get('/v1/documents/' + text['document_id'] + '/pages/1.png').status_code == 400
