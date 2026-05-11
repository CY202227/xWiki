"""Runtime configuration for the xWiki service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv


load_dotenv()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class XWikiConfig:
    """Strongly typed settings loaded from env vars and constructor overrides."""

    workspace: str = "data/my_kb"
    llm_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1")
    llm_api_key: str = os.getenv("OPENAI_API_KEY", "")
    llm_base_url: str = os.getenv("OPENAI_BASE_URL", "")
    llm_timeout: int = _env_int("XWIKI_LLM_TIMEOUT", 60)
    llm_max_retries: int = _env_int("XWIKI_LLM_MAX_RETRIES", 3)
    db_filename: str = os.getenv("XWIKI_DB_FILENAME", "xwiki.sqlite")
    table_prefix: str = os.getenv("XWIKI_TABLE_PREFIX", "xwiki")
    ingest_concurrency: int = _env_int("XWIKI_INGEST_CONCURRENCY", 5)
    compile_batch_size: int = _env_int("XWIKI_COMPILE_BATCH_SIZE", 4)
    processor_version: str = os.getenv(
        "XWIKI_PROCESSOR_VERSION", "2026.05.11.service-v1"
    )
    enable_reports: bool = _env_bool("XWIKI_ENABLE_REPORTS", True)
    allow_unsafe_file_stems: bool = _env_bool("XWIKI_ALLOW_UNSAFE_FILE_STEMS", False)

    def resolve_workspace(self) -> Path:
        return Path(self.workspace).expanduser().resolve()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "workspace": self.workspace,
            "llm_model": self.llm_model,
            "llm_api_key": self.llm_api_key,
            "llm_base_url": self.llm_base_url,
            "llm_timeout": self.llm_timeout,
            "llm_max_retries": self.llm_max_retries,
            "db_filename": self.db_filename,
            "table_prefix": self.table_prefix,
            "ingest_concurrency": self.ingest_concurrency,
            "compile_batch_size": self.compile_batch_size,
            "processor_version": self.processor_version,
            "enable_reports": self.enable_reports,
            "allow_unsafe_file_stems": self.allow_unsafe_file_stems,
        }

    def merge(self, overrides: Optional[dict[str, Any]] = None) -> "XWikiConfig":
        if not overrides:
            return self
        return XWikiConfig(**(self.as_dict() | overrides))
