"""Optional lightweight polling watcher used by embedding environments."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable


class InboxPoller:
    """Very small poll loop that triggers when inbox content changes."""

    def __init__(
        self, inbox_dir: Path, on_change: Callable[[], None], interval: float = 5.0
    ):
        self._dir = inbox_dir
        self._on_change = on_change
        self._interval = interval
        self._state = {}

    async def run_once(self) -> bool:
        current = {p: p.stat().st_mtime for p in self._dir.glob("*")}
        changed = current != self._state
        if changed:
            self._state = current
            self._on_change()
        return changed

    async def run_forever(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self._interval)
