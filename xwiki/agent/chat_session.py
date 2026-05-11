"""Minimal persistent chat session store for ask() history."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json

from ..db import XWikiDatabase


@dataclass
class SessionMessage:
    role: str
    content: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class ChatSessionStore:
    def __init__(self, db: XWikiDatabase, session_id: str):
        self._db = db
        self._session_id = session_id

    def upsert(self, messages: list[SessionMessage]) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO xwiki_query_sessions "
                "(session_id, created_at, updated_at, metadata_json) VALUES (?, ?, ?, ?)",
                (
                    self._session_id,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                    json.dumps({"turns": len(messages)}, ensure_ascii=False),
                ),
            )
            conn.commit()

    def append_turn(self, role: str, content: str) -> None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT metadata_json FROM xwiki_query_sessions WHERE session_id = ?",
                (self._session_id,),
            ).fetchone()
            if row and isinstance(row[0], str):
                payload = json.loads(row[0])
                created_at = payload.get("created_at", datetime.now().isoformat())
            else:
                created_at = datetime.now().isoformat()
                payload = {}
            payload["turns"] = payload.get("turns", 0) + 1
            payload["last_role"] = role
            payload["last_content"] = content
            payload["updated_at"] = datetime.now().isoformat()
            if "created_at" not in payload:
                payload["created_at"] = created_at
            conn.execute(
                "INSERT OR REPLACE INTO xwiki_query_sessions "
                "(session_id, created_at, updated_at, metadata_json) VALUES (?, ?, ?, ?)",
                (
                    self._session_id,
                    payload.get("created_at", datetime.now().isoformat()),
                    datetime.now().isoformat(),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            conn.commit()
