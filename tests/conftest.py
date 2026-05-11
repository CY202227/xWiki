"""Common fixtures for xWiki service tests."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Generator

import pytest

from xwiki import XWikiConfig, XWikiService


@pytest.fixture
def workspace_root() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory(prefix="xwiki-tests-") as root:
        yield Path(root)


@pytest.fixture
def service(workspace_root: Path) -> Generator[XWikiService, None, None]:
    cfg = XWikiConfig(workspace=str(workspace_root), llm_api_key="", llm_base_url="")
    service = XWikiService(cfg)
    yield service
