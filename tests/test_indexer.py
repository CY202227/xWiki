"""Indexing behavior without LLM credentials."""

from __future__ import annotations

import asyncio

from xwiki.converter import MarkdownConverter


def test_indexer_records_rows(service):
    file_path = service.workspace.paths.raw_dir / "one.md"
    file_path.write_text("# doc\n内容\n", encoding="utf-8")
    parsed = MarkdownConverter().parse_file(file_path)
    stats = asyncio.run(service.indexer.index_all([parsed]))
    assert stats["added"] == 1
    overview = service.searcher.get_overview()
    assert overview["totals"]["documents"] == 1
