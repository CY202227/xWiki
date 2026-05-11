"""Optional manual smoke runner."""

from __future__ import annotations

import asyncio

from .service import XWikiService


async def _main() -> None:
    service = XWikiService()
    print(service.run_smoke())
    await service.ingest_inbox()
    await service.compile_knowledge()
    print(service.run_smoke())


if __name__ == "__main__":
    asyncio.run(_main())
