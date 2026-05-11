"""Converter normalization tests."""

from __future__ import annotations

from xwiki.converter import MarkdownConverter


def test_split_pages_marker():
  text = "# a\n<!-- PAGE_1 -->\n第一页\n<!-- PAGE_2 -->\n第二页"
  pages = MarkdownConverter.split_pages(text)
  assert len(pages) == 2
  assert pages[0].page_no == 1
  assert "第一页" in pages[0].content


def test_clean_base64_image():
  text = "hello ![img](data:image/png;base64,abcd1234)== end"
  cleaned = MarkdownConverter.clean_text(text)
  assert "[IMAGE_REMOVED]" in cleaned
