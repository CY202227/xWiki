"""Real synthetic files exercise local MarkItDown parsing and locator integrity."""
import asyncio
import json

import pytest

pytest.importorskip("markitdown")
pytest.importorskip("pypdf")
docx = pytest.importorskip("docx")
canvas = pytest.importorskip("reportlab.pdfgen.canvas")

from xwiki import documents
from xwiki.agent.query import normalize_citations


def pdf(path):
    writer = canvas.Canvas(str(path))
    writer.drawString(50, 750, "Quasar water rule: 12 litres, not for drinking.")
    writer.showPage()
    writer.drawString(50, 750, "Inspect the storage tank every quarter.")
    writer.save()


def word(path):
    document = docx.Document()
    document.add_heading("Quasar garden", level=1)
    document.add_paragraph("Water is for plants, not for drinking.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Inspection"
    table.cell(0, 1).text = "Interval"
    table.cell(1, 0).text = "Tank"
    table.cell(1, 1).text = "Quarterly"
    document.save(path)


def test_pdf_physical_pages_and_original_archive(service, monkeypatch):
    import requests
    monkeypatch.setattr(requests.Session, "request", lambda *a, **k: pytest.fail("Local conversion must not access the network"))
    path = service.workspace.paths.inbox_dir / "quasar.pdf"
    pdf(path)
    original = path.read_bytes()
    parsed = service.converter.parse_file(path)
    assert [page.locator["page"] for page in parsed.pages] == [1, 2]
    assert "12" in parsed.pages[0].content
    assert "quarter" in parsed.pages[1].content
    result = asyncio.run(service.ingest_inbox())
    assert result.stats["added"] == 1
    record = service.list_documents()[0]
    from pathlib import Path
    assert Path(record["raw_path"]).read_bytes() == original
    assert service.query_documents("Quasar")
    assert "PDF page 2" in service.searcher.read_pages(record["document_id"], [2])
    path.write_bytes(original)
    assert asyncio.run(service.ingest_inbox()).stats["skipped"] == 1


def test_docx_blocks_tables_and_canonical_citations(service):
    path = service.workspace.paths.inbox_dir / "garden.docx"
    word(path)
    result = asyncio.run(service.ingest_inbox())
    assert result.stats["added"] == 1
    source = service.list_documents()[0]
    passages = service.searcher.document_passages(source["document_id"], ["drinking"], limit=3)
    assert passages[0]["page_no"] == 2
    assert passages[0]["locator"]["kind"] == "docx_block"
    assert any(item["locator"]["block_type"] == "table" and "Quarterly" in item["content"] for item in passages)
    reference = {"document_id": source["document_id"], "page_no": 2, "quote": "Water is for plants, not for drinking."}
    service.update_entity("Water", f"Water is for plants. [{source['document_id']} p.2]", base_version=None, reason="create", sources=[source["document_id"]], citations=[reference])
    page = service.read_entity("Water")
    assert f"[{source['document_id']} s.2]" in page["markdown"]
    citations = json.loads(page["entity"]["citations_json"])
    assert citations[0]["locator"]["block"] == 2
    assert "not a physical page" in service.searcher.read_pages(source["document_id"], [2])
    with pytest.raises(ValueError, match="locator"):
        service.update_entity("Water", "wrong", base_version=page["version"], reason="bad locator", sources=[source["document_id"]],
                              citations=[{**reference, "locator": {"kind": "pdf_page", "page": 2}}])


def test_failed_document_conversion_preserves_inbox(service):
    path = service.workspace.paths.inbox_dir / "broken.pdf"
    path.write_bytes(b"not a PDF")
    result = asyncio.run(service.ingest_inbox())
    assert result.stats["failed"] == 1
    assert path.read_bytes() == b"not a PDF"
    assert service.list_documents() == []


def test_blank_pdf_and_document_budgets_fail_closed(service, monkeypatch):
    from pypdf import PdfWriter
    path = service.workspace.paths.inbox_dir / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(path)
    with pytest.raises(ValueError, match="OCR"):
        service.converter.parse_file(path)
    monkeypatch.setattr(documents, "MAX_BYTES", 1)
    with pytest.raises(ValueError, match="32 MiB"):
        service.converter.parse_file(path)


def test_docx_marker_text_does_not_create_fake_pdf_pages(service):
    path = service.workspace.paths.inbox_dir / "markers.docx"
    document = docx.Document()
    document.add_paragraph("<!-- PAGE_999 --> original marker text")
    document.save(path)
    parsed = service.converter.parse_file(path)
    assert [page.page_no for page in parsed.pages] == [1]
    answer, repaired = normalize_citations("[doc p.1]", {("doc", 1)}, {("doc", 1): "s"})
    assert answer == "[doc s.1]" and repaired == 1


def test_missing_optional_dependency_gives_install_hint(service, monkeypatch):
    import sys
    path = service.workspace.paths.inbox_dir / "text.pdf"
    pdf(path)
    monkeypatch.setitem(sys.modules, "markitdown", None)
    result = asyncio.run(service.ingest_inbox())
    assert result.stats["failed"] == 1
    assert "xwiki[documents]" in result.stats["errors"][0]["error"]
    assert path.exists()


@pytest.mark.parametrize("extension", ["pdf", "docx"])
def test_image_content_requires_explicit_ocr(service, extension):
    import io
    from PIL import Image
    image = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(image, format="PNG")
    image.seek(0)
    path = service.workspace.paths.inbox_dir / f"image.{extension}"
    if extension == "pdf":
        from reportlab.lib.utils import ImageReader
        writer = canvas.Canvas(str(path))
        writer.drawString(50, 750, "Some text beside an image")
        writer.drawImage(ImageReader(image), 50, 600, width=20, height=20)
        writer.save()
    else:
        document = docx.Document()
        document.add_paragraph("Some text beside an image")
        document.add_picture(image)
        document.save(path)
    result = asyncio.run(service.ingest_inbox())
    assert result.stats["failed"] == 1
    assert "OCR" in result.stats["errors"][0]["error"]
    assert path.exists() and service.list_documents() == []
