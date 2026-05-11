"""Deterministic lint checks for data quality."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .db import XWikiDatabase


class StructuralLinter:
    def __init__(self, db: XWikiDatabase, report_dir: Path):
        self._db = db
        self._report_dir = report_dir

    def check_orphans(self):
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT l.entity_name "
                "FROM xwiki_entity_links l "
                "LEFT JOIN xwiki_entities e "
                "ON e.entity_name = l.entity_name "
                "WHERE e.entity_name IS NULL"
            ).fetchall()
        return {"count": len(rows), "items": [row["entity_name"] for row in rows]}

    def check_stale(self, stale_days: int = 365):
        threshold = datetime.now().replace(microsecond=0)
        from datetime import timedelta

        marker = (threshold - timedelta(days=stale_days)).date().isoformat()
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT entity_name, updated_at FROM xwiki_entities "
                "WHERE updated_at < ? ORDER BY updated_at",
                (marker,),
            ).fetchall()
        return {"count": len(rows), "items": [dict(r) for r in rows]}

    def check_unread_source_pages(self):
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT d.document_id, d.title "
                "FROM xwiki_documents d "
                "LEFT JOIN xwiki_pages p ON d.document_id = p.document_id "
                "WHERE p.document_id IS NULL"
            ).fetchall()
        return {"count": len(rows), "items": [dict(r) for r in rows]}

    def run(self):
        result = {
            "orphans": self.check_orphans(),
            "stale_entities": self.check_stale(),
            "missing_pages": self.check_unread_source_pages(),
        }
        return result
