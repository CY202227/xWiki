"""Document converter and page splitting helpers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List

from .images import strip_embedded_base64_images


@dataclass(frozen=True)
class ParsedDocument:
  document_id: str
  title: str
  source_path: Path
  raw_path: Path
  content_hash: str
  pages: list["ParsedPage"]
  raw_text: str


@dataclass(frozen=True)
class ParsedPage:
  page_no: int
  content: str


class MarkdownConverter:
  """Normalize raw markdown documents into clean, page-addressable chunks."""

  @staticmethod
  def clean_text(raw: str) -> str:
    return strip_embedded_base64_images(raw)

  @staticmethod
  def split_pages(raw_text: str) -> list[ParsedPage]:
    if "<!-- PAGE_" not in raw_text:
      return [ParsedPage(page_no=1, content=raw_text.strip())]

    parts = re.split(r"<!-- PAGE_(\d+) -->", raw_text)
    pages: list[ParsedPage] = []
    for i in range(1, len(parts), 2):
      try:
        page_no = int(parts[i])
      except ValueError:
        continue
      content = parts[i + 1] if i + 1 < len(parts) else ""
      pages.append(ParsedPage(page_no=page_no, content=content.strip()))
    if not pages:
      pages.append(ParsedPage(page_no=1, content=raw_text.strip()))
    return pages

  @staticmethod
  def build_document_id(raw_path: Path) -> str:
    return hashlib.md5(str(raw_path).encode("utf-8")).hexdigest()

  def parse_file(self, path: Path) -> ParsedDocument:
    raw = path.read_text(encoding="utf-8", errors="replace")
    cleaned = self.clean_text(raw)
    pages = self.split_pages(cleaned)
    content_hash = hashlib.md5(cleaned.encode("utf-8")).hexdigest()
    return ParsedDocument(
        document_id=self.build_document_id(path),
        title=path.stem.replace("_", " "),
        source_path=path,
        raw_path=path,
        content_hash=content_hash,
        pages=pages,
        raw_text=cleaned,
    )
