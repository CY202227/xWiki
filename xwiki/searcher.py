"""Read-focused retrieval facade."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .db import XWikiDatabase

logger = logging.getLogger(__name__)


class XWikiSearcher:
    def __init__(self, db: XWikiDatabase):
        self._db = db

    @staticmethod
    def _tokenize(query: str) -> List[str]:
        raw = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{2,}|[0-9]+", query)
        seen = set()
        tokens: List[str] = []
        for token in raw:
            if token in seen:
                continue
            seen.add(token)
            tokens.append(token)
        return tokens

    def get_overview(self) -> Dict[str, Any]:
        with self._db.connection() as conn:
            totals = {
                "documents": conn.execute(
                    "SELECT COUNT(*) FROM xwiki_documents"
                ).fetchone()[0],
                "entities": conn.execute(
                    "SELECT COUNT(*) FROM xwiki_entities"
                ).fetchone()[0],
                "pages": conn.execute("SELECT COUNT(*) FROM xwiki_pages").fetchone()[0],
            }
            domains = conn.execute(
                "SELECT domain, COUNT(*) FROM xwiki_entities GROUP BY domain ORDER BY COUNT(*) DESC LIMIT 20"
            ).fetchall()
            doc_types = conn.execute(
                "SELECT doc_type, COUNT(*) FROM xwiki_documents GROUP BY doc_type ORDER BY COUNT(*) DESC LIMIT 20"
            ).fetchall()
            return {
                "totals": totals,
                "top_domains": dict(domains),
                "top_doc_types": dict(doc_types),
            }

    def _fts(
        self, conn: sqlite3.Connection, query: str, limit: int
    ) -> List[Dict[str, Any]]:
        rows = conn.execute(
            "SELECT document_id, title, summary, snippet(xwiki_fts, 3, '[', ']', '...', 40) "
            "as context_snippet FROM xwiki_fts WHERE xwiki_fts MATCH ? LIMIT ?",
            (query, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def _like(
        self, conn: sqlite3.Connection, tokens: list[str], limit: int
    ) -> List[Dict[str, Any]]:
        if not tokens:
            return []
        terms = []
        params: List[str] = []
        for token in tokens:
            wildcard = f"%{token}%"
            terms.append("(title LIKE ? OR summary LIKE ?)")
            params.extend([wildcard, wildcard])
        params.append(limit)
        sql = f"SELECT document_id, title, doc_type, summary as context_snippet FROM xwiki_documents WHERE {' OR '.join(terms)} LIMIT ?"
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def search_documents(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        tokens = self._tokenize(query)
        if not tokens:
            return []
        with self._db.connection() as conn:
            try:
                strict = self._fts(conn, " AND ".join(tokens), limit)
                if strict:
                    return strict
                broad = self._fts(conn, " OR ".join(tokens), limit)
                if broad:
                    return broad
            except sqlite3.OperationalError as error:
                logger.warning("fts failed, fallback to LIKE: %s", error)
            return self._like(conn, tokens, limit)

    def search_wiki(self, query: str, limit: int = 12) -> List[Dict[str, Any]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT entity_name, domain, consensus_summary, attributes_json, source_links_json, updated_at "
                "FROM xwiki_entities WHERE entity_name LIKE ? OR consensus_summary LIKE ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (f"%{query}%", f"%{query}%", limit),
            ).fetchall()
            items = [dict(row) for row in rows]
            if len(items) >= limit:
                return items
            for token in self._tokenize(query):
                extra = conn.execute(
                    "SELECT entity_name, domain, consensus_summary, attributes_json, source_links_json, updated_at "
                    "FROM xwiki_entities WHERE entity_name LIKE ? OR consensus_summary LIKE ? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (f"%{token}%", f"%{token}%", limit - len(items)),
                ).fetchall()
                for row in extra:
                    payload = dict(row)
                    if all(e["entity_name"] != payload["entity_name"] for e in items):
                        items.append(payload)
                        if len(items) >= limit:
                            return items
            return items

    def read_pages(self, document_id: str, page_nos: list[int]) -> str:
        if not page_nos:
            return ""
        placeholders = ",".join(["?"] * len(page_nos))
        with self._db.connection() as conn:
            rows = conn.execute(
                f"SELECT page_no, content FROM xwiki_pages WHERE document_id = ? "
                f"AND page_no IN ({placeholders}) ORDER BY page_no",
                [document_id] + page_nos,
            ).fetchall()
            return "\n\n".join(
                [f"--- Page {row['page_no']} ---\n{row['content']}" for row in rows]
            )

    def get_entity_evidence(self, entity_name: str, limit: int = 3) -> Dict[str, Any]:
        with self._db.connection() as conn:
            entity = conn.execute(
                "SELECT * FROM xwiki_entities WHERE entity_name = ?",
                (entity_name,),
            ).fetchone()
            if not entity:
                return {"error": "Entity not found"}
            links = conn.execute(
                "SELECT d.document_id, d.title, d.doc_date, d.summary "
                "FROM xwiki_entity_links l "
                "JOIN xwiki_documents d ON l.document_id = d.document_id "
                "WHERE l.entity_name = ? ORDER BY d.doc_date DESC LIMIT ?",
                (entity_name, limit),
            ).fetchall()
            result = dict(entity)
            result["evidence"] = [dict(r) for r in links]
            result["wiki_consensus"] = result.pop("consensus_summary")
            return result

    def get_recent_activity(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT event_type, description, payload_json, created_at "
                "FROM xwiki_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
