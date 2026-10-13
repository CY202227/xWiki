"""Optional, local-only MarkItDown conversion with original source locators."""
from __future__ import annotations

import copy
import hashlib
import io
import zipfile
from importlib.metadata import version
from pathlib import Path
from xml.etree import ElementTree

from .converter import MarkdownConverter, ParsedDocument, ParsedPage

MAX_BYTES = 32 * 1024 * 1024
MAX_UNITS = 200
MAX_TEXT = 2_000_000


def convert_document(path: Path) -> ParsedDocument:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Document exceeds the 32 MiB conversion limit")
    try:
        from markitdown import MarkItDown
    except ImportError as error:
        raise ValueError('PDF/DOCX support requires pip install "xwiki[documents]"') from error
    raw = path.read_bytes()
    converter = MarkItDown(enable_plugins=False)
    metadata = {"format": path.suffix.lower().lstrip("."), "converter": "markitdown", "version": version("markitdown"), "extraction": "text", "ocr": False}

    def text(data: bytes, extension: str) -> str:
        result = converter.convert_stream(io.BytesIO(data), file_extension=extension)
        cleaned = MarkdownConverter.clean_text(result.text_content).strip()
        if not cleaned:
            raise ValueError("Empty conversion requires OCR or source review; original input is preserved")
        if len(cleaned) > MAX_TEXT:
            raise ValueError("Converted source unit exceeds the text budget")
        return cleaned

    pages = []
    try:
        if path.suffix.lower() == ".pdf":
            from pypdf import PdfReader, PdfWriter
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_UNITS:
                raise ValueError("PDF must be unencrypted and contain 1-200 pages")
            for number, page in enumerate(reader.pages, 1):
                if page.images:
                    raise ValueError("PDF image content requires OCR or source review")
                writer = PdfWriter()
                writer.add_page(page)
                buffer = io.BytesIO()
                writer.write(buffer)
                content = text(buffer.getvalue(), ".pdf")
                pages.append(ParsedPage(number, content, {"kind": "pdf_page", "page": number, "label": f"PDF page {number}", "citation_prefix": "p", **metadata}))
        else:
            from defusedxml.ElementTree import fromstring
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if sum(item.file_size for item in archive.infolist()) > 128 * 1024 * 1024:
                    raise ValueError("DOCX expanded content exceeds 128 MiB")
                document = fromstring(archive.read("word/document.xml"))
                namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
                body = document.find(namespace + "body")
                if body is None:
                    raise ValueError("DOCX has no document body")
                blocks = [item for item in body if item.tag in {namespace + "p", namespace + "tbl"}]
                if not 1 <= len(blocks) <= MAX_UNITS:
                    raise ValueError("DOCX must contain 1-200 paragraph/table blocks")
                for number, block in enumerate(blocks, 1):
                    if any(node.tag in {namespace + "drawing", namespace + "pict"} for node in block.iter()):
                        raise ValueError("DOCX image content requires OCR or source review")
                    if not any(node.text and node.text.strip() for node in block.iter(namespace + "t")):
                        if any(node.tag == namespace + "drawing" for node in block.iter()):
                            raise ValueError("Image-only DOCX block requires OCR or source review")
                        continue
                    fragment = copy.deepcopy(document)
                    fragment_body = fragment.find(namespace + "body")
                    assert fragment_body is not None
                    fragment_body.clear()
                    fragment_body.append(copy.deepcopy(block))
                    buffer = io.BytesIO()
                    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as output:
                        for item in archive.infolist():
                            output.writestr(item.filename, ElementTree.tostring(fragment, encoding="utf-8", xml_declaration=True)
                                            if item.filename == "word/document.xml" else archive.read(item.filename))
                    content = text(buffer.getvalue(), ".docx")
                    kind = "table" if block.tag == namespace + "tbl" else "paragraph"
                    pages.append(ParsedPage(number, content, {"kind": "docx_block", "block": number, "block_type": kind,
                                 "label": f"DOCX body {kind} block {number} (not a physical page)", "citation_prefix": "s", **metadata}))
        if not pages or sum(len(page.content) for page in pages) > MAX_TEXT:
            raise ValueError("Document has no extractable text or exceeds the 2 million character budget")
    except (ValueError, ImportError) as error:
        raise ValueError(f"Document conversion failed: {error}") from error
    except Exception as error:
        raise ValueError(f"Document conversion failed ({type(error).__name__}); original input is preserved") from error
    return ParsedDocument(MarkdownConverter.build_document_id(path), path.stem.replace("_", " "), path, path,
                          hashlib.sha256(raw).hexdigest(), pages, "\n\n".join(page.content for page in pages), metadata)
