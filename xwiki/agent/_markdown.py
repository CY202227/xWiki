"""Lightweight markdown text cleanup helpers."""

from __future__ import annotations

import re


def normalize_newlines(text: str) -> str:
    return re.sub(r"\r\n", "\n", text).strip()


def truncate(text: str, limit: int = 600) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
