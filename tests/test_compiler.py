"""Compiler fallback path when LLM is unavailable."""

from __future__ import annotations

import asyncio


def test_compile_no_entities_without_credentials(service):
    service.workspace.paths.inbox_dir.joinpath("a.md").write_text(
        "#A\n内容", encoding="utf-8"
    )
    asyncio.run(service.ingest_inbox())
    summary = asyncio.run(service.compile_knowledge())
    assert summary.operation == "compile_knowledge"
    assert summary.stats["documents_seen"] >= 1
