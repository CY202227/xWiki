"""Deterministic lint checks for data quality."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import hashlib

from .renderer import entity_file_name, _slugify

from .db import XWikiDatabase


class StructuralLinter:
    def __init__(self, db: XWikiDatabase, report_dir: Path):
        self._db = db
        self._report_dir = report_dir

    def check_orphans(self):
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT e.entity_name FROM xwiki_entities e "
                "WHERE NOT EXISTS (SELECT 1 FROM xwiki_entity_links l JOIN xwiki_documents d "
                "ON d.document_id=l.document_id WHERE l.entity_name=e.entity_name)"
            ).fetchall()
        return {"count": len(rows), "items": [row["entity_name"] for row in rows]}

    def check_dangling_links(self):
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT l.entity_name, l.document_id FROM xwiki_entity_links l "
                "LEFT JOIN xwiki_entities e ON e.entity_name=l.entity_name "
                "LEFT JOIN xwiki_documents d ON d.document_id=l.document_id "
                "WHERE e.entity_name IS NULL OR d.document_id IS NULL"
            ).fetchall()
        return {"count": len(rows), "items": [dict(row) for row in rows]}

    def check_entity_files(self):
        root = self._report_dir.parent / "entities"
        missing, modified = [], []
        with self._db.connection() as conn:
            rows = conn.execute("SELECT e.entity_name, f.relative_path, f.content_hash FROM xwiki_entities e LEFT JOIN xwiki_entity_files f ON e.entity_name=f.entity_name").fetchall()
        for row in rows:
            path = root / (row["relative_path"] or entity_file_name(row["entity_name"]))
            if not row["relative_path"] and not path.exists():
                path = root / f"{_slugify(row['entity_name'])}.md"
            if path.is_symlink() or path.resolve().parent != root.resolve():
                modified.append({"entity_name": row["entity_name"], "reason": "invalid path"})
            elif not path.exists():
                missing.append(row["entity_name"])
            elif row["content_hash"] and hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest() != row["content_hash"]:
                modified.append({"entity_name": row["entity_name"], "reason": "file differs from saved version"})
        return {"missing": missing, "modified": modified, "count": len(missing) + len(modified)}

    def check_citations(self):
        from .searcher import XWikiSearcher
        searcher = XWikiSearcher(self._db)
        missing, invalid = [], []
        with self._db.connection() as conn:
            names = [row[0] for row in conn.execute("SELECT entity_name FROM xwiki_entities")]
        for name in names:
            try:
                evidence = searcher.get_entity_evidence(name)
                if not evidence["citations"]:
                    missing.append(name)
                for citation in evidence["citations"]:
                    if not citation["valid"]:
                        invalid.append({"entity_name": name, "citation": citation})
            except (ValueError, KeyError, TypeError) as error:
                invalid.append({"entity_name": name, "error": str(error)})
        return {"count": len(missing) + len(invalid), "missing": missing, "invalid": invalid}

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
            "dangling_links": self.check_dangling_links(),
            "entity_files": self.check_entity_files(),
            "citations": self.check_citations(),
        }
        return result
