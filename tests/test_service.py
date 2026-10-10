"""Smoke-level service coverage."""

from __future__ import annotations

import asyncio
import pytest


def test_service_init_and_status(service):
    status = service.status()
    assert status["workspace"] == str(service.workspace.paths.root)
    assert status["totals"]["documents"] == 0
    assert status["totals"]["entities"] == 0


def test_ingest_from_inbox(service):
    inbox_file = service.workspace.paths.inbox_dir / "policy.md"
    inbox_file.write_text("# 标题\n\n测试文档", encoding="utf-8")
    result = asyncio.run(service.ingest_inbox())
    assert result.operation == "ingest_inbox"
    status = service.status()
    assert status["totals"]["documents"] == 1


def test_ingest_duplicate_content_has_one_source(service):
    for name in ("first.md", "second.md"):
        service.workspace.paths.inbox_dir.joinpath(name).write_text("相同来源", encoding="utf-8")
    result = asyncio.run(service.ingest_inbox())
    assert result.stats["added"] == 1
    assert result.stats["skipped"] == 1
    assert service.status()["totals"]["documents"] == 1
    assert list(service.workspace.paths.inbox_dir.iterdir()) == []


def test_failed_ingestion_retains_input_and_reuses_archive(service, monkeypatch):
    path = service.workspace.paths.inbox_dir / "retry.md"
    path.write_text("可恢复来源", encoding="utf-8")
    index = service.indexer.index

    async def fail(document):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(service.indexer, "index", fail)
    result = asyncio.run(service.ingest_inbox(clean_inbox=True))
    assert result.stats["failed"] == 1
    assert path.exists()
    archives = list(service.workspace.paths.raw_dir.iterdir())
    assert len(archives) == 1
    monkeypatch.setattr(service.indexer, "index", index)
    result = asyncio.run(service.ingest_inbox())
    assert result.stats["added"] == 1
    assert not path.exists()
    assert list(service.workspace.paths.raw_dir.iterdir()) == archives


def test_invalid_encoding_does_not_corrupt_source(service):
    path = service.workspace.paths.inbox_dir / "invalid.md"
    path.write_bytes(b'\xff\xfeinvalid')
    result = asyncio.run(service.ingest_inbox())
    assert result.stats["failed"] == 1
    assert path.read_bytes() == b'\xff\xfeinvalid'


def test_invalid_compile_batch_size_is_rejected(service):
    with pytest.raises(ValueError):
        asyncio.run(service.compile_knowledge(batch_size=0))
