"""Read-focused retrieval facade."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from typing import Any, Dict, List

from .db import XWikiDatabase

logger = logging.getLogger(__name__)


class XWikiSearcher:
    def __init__(self, db: XWikiDatabase):
        self._db = db

    @staticmethod
    def _tokenize(query: str) -> List[str]:
        raw = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+", query.casefold())
        expanded = []
        stop = {"什么", "么是", "如何", "怎么", "哪些", "是否", "以及", "的"}
        for token in raw:
            expanded.append(token)
            if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
                expanded.extend(token[i:i + 2] for i in range(len(token) - 1))
        seen = set()
        tokens: List[str] = []
        for token in expanded:
            if token in seen or token in stop:
                continue
            seen.add(token)
            tokens.append(token)
        return tokens[:64]

    @staticmethod
    def _validate_query(query: str, limit: int) -> None:
        if len(query) > 500:
            raise ValueError("Query must not exceed 500 characters")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

    @staticmethod
    def _wildcard(token: str) -> str:
        return "%" + token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

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
            "as context_snippet FROM xwiki_fts WHERE xwiki_fts MATCH ? AND document_id IN (SELECT document_id FROM xwiki_documents WHERE status='indexed') "
            "ORDER BY bm25(xwiki_fts), document_id LIMIT ?",
            (query, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def _like(
        self, conn: sqlite3.Connection, tokens: list[str], limit: int
    ) -> List[Dict[str, Any]]:
        if not tokens:
            return []
        terms = []
        scores = []
        params = []
        score_params = []
        for token in tokens:
            wildcard = self._wildcard(token)
            match = "(d.title LIKE ? ESCAPE '\\' OR d.summary LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM xwiki_pages p WHERE p.document_id=d.document_id AND p.content LIKE ? ESCAPE '\\'))"
            terms.append(match)
            scores.append("(CASE WHEN d.title LIKE ? ESCAPE '\\' THEN 5 ELSE 0 END + CASE WHEN d.summary LIKE ? ESCAPE '\\' THEN 2 ELSE 0 END + CASE WHEN EXISTS (SELECT 1 FROM xwiki_pages p WHERE p.document_id=d.document_id AND p.content LIKE ? ESCAPE '\\') THEN 1 ELSE 0 END)")
            params.extend([wildcard] * 3)
            score_params.extend([wildcard] * 3)
        sql = f"SELECT d.document_id, d.title, d.doc_type, d.summary, ({' + '.join(scores)}) AS score FROM xwiki_documents d WHERE d.status='indexed' AND ({' OR '.join(terms)}) ORDER BY score DESC, d.document_id LIMIT ?"
        rows = conn.execute(sql, [*score_params, *params, limit]).fetchall()
        hits = [dict(row) for row in rows]
        for hit in hits:
            passages = self.document_passages(hit["document_id"], tokens, limit=1)
            hit["context_snippet"] = passages[0]["content"] if passages else hit["summary"]
        return hits

    def search_documents(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        self._validate_query(query, limit)
        tokens = self._tokenize(query)
        if not tokens:
            return []
        with self._db.connection() as conn:
            try:
                quoted = ['"' + token.replace('"', '""') + '"' for token in tokens]
                strict = self._fts(conn, " AND ".join(quoted), limit)
                if strict:
                    return strict
                broad = self._fts(conn, " OR ".join(quoted), limit)
                if broad:
                    return broad
            except sqlite3.OperationalError as error:
                logger.warning("fts failed, fallback to LIKE: %s", error)
            return self._like(conn, tokens, limit)

    def search_wiki(self, query: str, limit: int = 12) -> List[Dict[str, Any]]:
        self._validate_query(query, limit)
        tokens = self._tokenize(query)
        if not tokens:
            return []
        clauses = []
        scores = ["CASE WHEN entity_name = ? COLLATE NOCASE THEN 50 ELSE 0 END"]
        score_params = [query]
        params = []
        for token in tokens:
            clauses.append("(entity_name LIKE ? ESCAPE '\\' OR consensus_summary LIKE ? ESCAPE '\\' OR attributes_json LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\')")
            scores.append("(CASE WHEN entity_name LIKE ? ESCAPE '\\' THEN 5 ELSE 0 END + CASE WHEN consensus_summary LIKE ? ESCAPE '\\' THEN 1 ELSE 0 END)")
            params.extend([self._wildcard(token)] * 5)
            score_params.extend([self._wildcard(token)] * 2)
        current: list[dict[str, Any]] = []
        offset = 0
        batch_size = max(limit, 20)
        while len(current) < limit:
            with self._db.connection() as conn:
                rows = conn.execute(
                    "SELECT entity_name, page_id, domain, consensus_summary, body, summary, attributes_json, source_links_json, citations_json, updated_at, "
                    f"({' + '.join(scores)}) AS score FROM xwiki_entities WHERE ({' OR '.join(clauses)}) AND NOT EXISTS (SELECT 1 FROM xwiki_entity_links l LEFT JOIN xwiki_documents d ON d.document_id=l.document_id WHERE l.entity_name=xwiki_entities.entity_name AND (d.document_id IS NULL OR d.status!='indexed')) "
                    "ORDER BY score DESC, entity_name LIMIT ? OFFSET ?",
                    [*score_params, *params, batch_size, offset],
                ).fetchall()
            for row in rows:
                hit = dict(row)
                evidence = self.get_entity_evidence(hit["entity_name"])
                if not evidence.get("source_issues") and all(citation["valid"] for citation in evidence.get("citations", [])):
                    current.append(hit)
                    if len(current) == limit:
                        break
            if len(rows) < batch_size:
                break
            offset += len(rows)
        return current

    def list_entities(self, domain: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
        self._validate_query("", limit)
        if offset < 0:
            raise ValueError("offset must be nonnegative")
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT entity_name, page_id, domain, CASE WHEN summary='' THEN substr(consensus_summary, 1, 300) ELSE summary END AS summary, updated_at FROM xwiki_entities "
                "WHERE (? IS NULL OR domain=?) ORDER BY entity_name LIMIT ? OFFSET ?",
                (domain, domain, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def document_passages(self, document_id: str, tokens: list[str], limit: int = 2) -> list[dict]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT p.page_no, p.content, p.locator_json, d.content_hash FROM xwiki_pages p JOIN xwiki_documents d "
                "ON p.document_id=d.document_id WHERE p.document_id=? AND d.status='indexed' ORDER BY p.page_no", (document_id,),
            ).fetchall()
        ranked = sorted(rows, key=lambda row: -sum(token in row["content"].casefold() for token in tokens))
        passages = []
        for row in ranked[:limit]:
            content = row["content"]
            positions = [content.casefold().find(token) for token in tokens if token in content.casefold()]
            start = max(0, (min(positions) if positions else 0) - 150)
            passages.append({"document_id": document_id, "page_no": row["page_no"], "content": content[start:start + 1500], "content_hash": row["content_hash"], "locator": json.loads(row["locator_json"])})
        return passages

    def read_pages(self, document_id: str, page_nos: list[int]) -> str:
        if not page_nos:
            return ""
        if len(page_nos) > 20 or any(not isinstance(page, int) or page < 1 for page in page_nos):
            raise ValueError("Read between 1 and 20 positive page numbers per request")
        page_nos = list(dict.fromkeys(page_nos))
        placeholders = ",".join(["?"] * len(page_nos))
        with self._db.connection() as conn:
            rows = conn.execute(
                f"SELECT page_no, content, locator_json FROM xwiki_pages WHERE document_id = ? "
                f"AND page_no IN ({placeholders}) ORDER BY page_no",
                (document_id, *page_nos),
            ).fetchall()
            if len(rows) != len(page_nos):
                raise ValueError("Source document or requested pages do not exist")
            return "\n\n".join(
                [f"--- {json.loads(row['locator_json']).get('label', 'Page ' + str(row['page_no']))} ---\n{row['content']}" for row in rows]
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
                "WHERE l.entity_name = ? AND d.status='indexed' ORDER BY d.doc_date DESC LIMIT ?",
                (entity_name, limit),
            ).fetchall()
            result = dict(entity)
            result["source_issues"] = [dict(row) for row in conn.execute(
                "SELECT l.document_id, d.status AS source_status FROM xwiki_entity_links l LEFT JOIN xwiki_documents d "
                "ON d.document_id=l.document_id WHERE l.entity_name=? AND (d.document_id IS NULL OR d.status!='indexed')", (entity_name,))]
            review = conn.execute("SELECT review_json, fingerprint FROM xwiki_maintenance_tasks WHERE kind='page' AND subject=? AND status='review' "
                                  "AND error='Source changed; reconcile article evidence'", (entity["page_id"],)).fetchone()
            from .entities import entity_version
            if review and review["fingerprint"] == entity_version(dict(entity)):
                result["source_issues"].append({"review": json.loads(review[0])})
            result["evidence"] = [dict(r) for r in links]
            citations = json.loads(result.get("citations_json") or "[]")
            verified = []
            for citation in citations:
                page = conn.execute("SELECT p.content, p.locator_json, d.content_hash, d.status FROM xwiki_pages p JOIN xwiki_documents d ON p.document_id=d.document_id WHERE p.document_id=? AND p.page_no=?",
                                    (citation["document_id"], citation["page_no"])).fetchone()
                verified.append({**citation, "locator": json.loads(page["locator_json"]) if page else {}, "source_status": page["status"] if page else "missing", "valid": bool(page and page["status"] == "indexed" and citation["quote"] in page["content"] and citation.get("content_hash") == page["content_hash"])})
            result["citations"] = verified
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
