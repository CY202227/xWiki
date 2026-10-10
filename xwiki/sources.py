"""Audited source withdrawal and immutable replacement relationships."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .entities import WikiConflictError, entity_version


def mark_affected_pages(conn, document_id: str, timestamp: str, review: dict) -> list[dict]:
    pages = [dict(row) for row in conn.execute(
        "SELECT e.* FROM xwiki_entities e JOIN xwiki_entity_links l ON l.entity_name=e.entity_name WHERE l.document_id=?", (document_id,))]
    for page in pages:
        conn.execute(
            "INSERT INTO xwiki_maintenance_tasks(kind, subject, fingerprint, status, next_due, error, review_json) "
            "VALUES ('page', ?, ?, 'review', ?, ?, ?) ON CONFLICT(kind, subject) DO UPDATE SET "
            "fingerprint=excluded.fingerprint, status='review', next_due=excluded.next_due, stability=0, failure_count=0, "
            "error=excluded.error, review_json=excluded.review_json, plan_json=NULL, run_id=NULL, claimed_at=NULL",
            (page["page_id"], entity_version(page), timestamp, "Source changed; reconcile article evidence", json.dumps(review, ensure_ascii=False)))
    return pages


class SourceLifecycle:
    def __init__(self, db):
        self.db = db

    def transition(self, document_id: str, *, expected_hash: str, reason: str,
                   replacement_id: str | None = None, preview: bool = False) -> dict:
        if not expected_hash or not reason.strip() or len(reason) > 1000:
            raise ValueError("Expected source hash and a reason of 1-1000 characters are required")
        status = "superseded" if replacement_id else "withdrawn"
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.db.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            source = conn.execute("SELECT * FROM xwiki_documents WHERE document_id=?", (document_id,)).fetchone()
            if source is None:
                raise KeyError("Source not found")
            if source["content_hash"] != expected_hash or source["status"] != "indexed":
                raise WikiConflictError("Source changed or is already inactive; reread its status")
            if replacement_id:
                replacement = conn.execute("SELECT status FROM xwiki_documents WHERE document_id=?", (replacement_id,)).fetchone()
                if replacement_id == document_id or replacement is None or replacement[0] != "indexed":
                    raise ValueError("Replacement must be a different, active indexed source")
            pages = [dict(row) for row in conn.execute(
                "SELECT e.* FROM xwiki_entities e JOIN xwiki_entity_links l ON l.entity_name=e.entity_name WHERE l.document_id=?",
                (document_id,))]
            result = {"document_id": document_id, "status": status, "replacement_id": replacement_id,
                      "reason": reason, "affected_pages": [{"page_id": page["page_id"], "title": page["entity_name"]} for page in pages],
                      "preview": preview, "history_preserved": True}
            if preview:
                conn.rollback()
                return result
            conn.execute("UPDATE xwiki_documents SET status=?, updated_at=? WHERE document_id=?", (status, timestamp, document_id))
            conn.execute("INSERT INTO xwiki_source_events(document_id, content_hash, status, replacement_id, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                         (document_id, expected_hash, status, replacement_id, reason, timestamp))
            conn.execute("UPDATE xwiki_compile_state SET status=?, error=?, run_id=NULL, updated_at=? WHERE document_id=?",
                         (status, reason, timestamp, document_id))
            mark_affected_pages(conn, document_id, timestamp, result)
            conn.commit()
        return result

    def history(self, document_id: str) -> list[dict]:
        with self.db.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM xwiki_source_events WHERE document_id=? ORDER BY id", (document_id,))]

    def versions(self, document_id: str) -> list[dict]:
        with self.db.connection() as conn:
            return [{**dict(row), "document": json.loads(row["document_json"]), "pages": json.loads(row["pages_json"])}
                    for row in conn.execute("SELECT * FROM xwiki_source_versions WHERE document_id=? ORDER BY id", (document_id,))]
