"""Programmatic smoke script for the service API (non-CLI entry)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from xwiki import XWikiConfig, XWikiService


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    config = XWikiConfig(workspace=str(Path("data/my_kb")))
    service = XWikiService(config)
    logging.info("Smoke workspace: %s", config.workspace)
    logging.info("initial status: %s", service.status())

    logging.info("ingest_inbox started")
    ingest = await service.ingest_inbox()
    logging.info("ingest finished: %s", ingest)

    logging.info("compile_knowledge started")
    compile_result = await service.compile_knowledge()
    logging.info("compile finished: %s", compile_result)

    logging.info("structural lint started")
    lint_result = service.run_structural_lint()
    logging.info("lint finished: %s", lint_result)

    smoke = service.run_smoke()
    logging.info("smoke result: %s", smoke)
    logging.info("log file: %s", service.workspace.paths.log_file)


if __name__ == "__main__":
    asyncio.run(main())
