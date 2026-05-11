"""Event logging and markdown log rendering."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict

from .db import XWikiDatabase


class XWikiEventLog:
    def __init__(self, db: XWikiDatabase, wiki_log_path):
        self._db = db
        self._log_path = wiki_log_path

    def record(
        self,
        event_type: str,
        description: str,
        payload: Dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now().isoformat()
        with self._db.connection() as conn:
            conn.execute(
                "INSERT INTO xwiki_events (event_type, description, payload_json, created_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    event_type,
                    description,
                    json.dumps(payload or {}, ensure_ascii=False),
                    now,
                ),
            )
            conn.commit()
        line = f"[{now}] {event_type}: {description}\n"
        with self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def append_report(self, report: Dict[str, Any], filename: str) -> None:
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = filename if str(filename).endswith(".md") else f"{filename}.md"
        path = self._log_path.parent / "reports" / report_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
