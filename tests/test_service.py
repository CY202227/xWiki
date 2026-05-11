"""Smoke-level service coverage."""

from __future__ import annotations

import asyncio


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
