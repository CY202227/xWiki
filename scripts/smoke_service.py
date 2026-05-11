"""Programmatic smoke script for the service API (non-CLI entry)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from xwiki import XWikiConfig, XWikiService


async def main() -> None:
  config = XWikiConfig(workspace=str(Path("data/smoke_kb")))
  service = XWikiService(config)
  print("status", service.status())
  ingest = await service.ingest_inbox()
  print("ingest", ingest)
  compile_result = await service.compile_knowledge()
  print("compile", compile_result)
  print("lint", service.run_structural_lint())
  print("smoke", service.run_smoke())


if __name__ == "__main__":
  asyncio.run(main())
