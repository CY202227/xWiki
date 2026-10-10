"""Database bootstrap and connection helpers."""

from __future__ import annotations

import sqlite3
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Tuple


class XWikiSchema:
    @staticmethod
    def bootstrap(conn: sqlite3.Connection) -> None:
        schema = [
            """CREATE TABLE IF NOT EXISTS xwiki_documents (
            document_id TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            raw_path TEXT NOT NULL,
            title TEXT NOT NULL,
            canonical_title TEXT,
            doc_date TEXT,
            doc_type TEXT,
            summary TEXT,
            topic_tags_json TEXT,
            outline_json TEXT,
            page_summaries_json TEXT,
            content_hash TEXT,
            processor_version TEXT,
            status TEXT DEFAULT 'new',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
          )""",
            """CREATE TABLE IF NOT EXISTS xwiki_pages (
            document_id TEXT NOT NULL,
            page_no INTEGER NOT NULL,
            content TEXT NOT NULL,
            PRIMARY KEY (document_id, page_no)
          )""",
            """CREATE TABLE IF NOT EXISTS xwiki_processing_cache (
            content_hash TEXT NOT NULL,
            page_no INTEGER NOT NULL,
            processor_version TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (content_hash, page_no, processor_version)
          )""",
            """CREATE VIRTUAL TABLE IF NOT EXISTS xwiki_fts USING fts5(
            document_id UNINDEXED, title, summary, raw_content
          )""",
            """CREATE TABLE IF NOT EXISTS xwiki_entities (
            entity_name TEXT PRIMARY KEY,
            domain TEXT,
            consensus_summary TEXT NOT NULL,
            attributes_json TEXT,
            source_links_json TEXT,
            updated_at TEXT NOT NULL,
            created_at TEXT NOT NULL
          )""",
            """CREATE TABLE IF NOT EXISTS xwiki_entity_links (
            entity_name TEXT NOT NULL,
            document_id TEXT NOT NULL,
            PRIMARY KEY (entity_name, document_id)
          )""",
            """CREATE TABLE IF NOT EXISTS xwiki_compile_state (
            document_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            updated_at TEXT NOT NULL
          )""",
            """CREATE TABLE IF NOT EXISTS xwiki_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            description TEXT NOT NULL,
            payload_json TEXT,
            created_at TEXT NOT NULL
          )""",
            """CREATE TABLE IF NOT EXISTS xwiki_query_sessions (
            session_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata_json TEXT
          )""",
            """CREATE TABLE IF NOT EXISTS xwiki_entity_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_name TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
          )""",
            """CREATE TABLE IF NOT EXISTS xwiki_entity_files (
            entity_name TEXT PRIMARY KEY,
            relative_path TEXT NOT NULL UNIQUE,
            content_hash TEXT NOT NULL
          )""",
            "CREATE INDEX IF NOT EXISTS xwiki_revision_entity ON xwiki_entity_revisions(entity_name, id)",
            "CREATE INDEX IF NOT EXISTS xwiki_link_document ON xwiki_entity_links(document_id)",
            "CREATE INDEX IF NOT EXISTS xwiki_document_hash ON xwiki_documents(content_hash)",
            """CREATE TABLE IF NOT EXISTS xwiki_wiki_links (
            source_id TEXT NOT NULL, target_id TEXT NOT NULL,
            PRIMARY KEY(source_id, target_id))""",
            """CREATE TABLE IF NOT EXISTS xwiki_maintenance_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, subject TEXT NOT NULL,
            fingerprint TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            next_due TEXT NOT NULL, stability INTEGER NOT NULL DEFAULT 0,
            run_id TEXT, claimed_at TEXT, error TEXT, plan_json TEXT,
            UNIQUE(kind, subject))""",
        ]
        for ddl in schema:
            conn.execute(ddl)
        task_columns = {row[1] for row in conn.execute("PRAGMA table_info(xwiki_maintenance_tasks)")}
        if "failure_count" not in task_columns:
            conn.execute("ALTER TABLE xwiki_maintenance_tasks ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0")
        if "review_json" not in task_columns:
            conn.execute("ALTER TABLE xwiki_maintenance_tasks ADD COLUMN review_json TEXT")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(xwiki_compile_state)")}
        for name in ("content_hash", "compiler_version", "run_id"):
            if name not in columns:
                conn.execute(f"ALTER TABLE xwiki_compile_state ADD COLUMN {name} TEXT")
        entity_columns = {row[1] for row in conn.execute("PRAGMA table_info(xwiki_entities)")}
        if "citations_json" not in entity_columns:
            conn.execute("ALTER TABLE xwiki_entities ADD COLUMN citations_json TEXT NOT NULL DEFAULT '[]'")
        for name, definition in (("page_id", "TEXT"), ("summary", "TEXT NOT NULL DEFAULT ''"),
                                 ("body", "TEXT NOT NULL DEFAULT ''"), ("related_json", "TEXT NOT NULL DEFAULT '[]'")):
            if name not in entity_columns:
                conn.execute(f"ALTER TABLE xwiki_entities ADD COLUMN {name} {definition}")
        import uuid
        for row in conn.execute("SELECT entity_name FROM xwiki_entities WHERE page_id IS NULL").fetchall():
            conn.execute("UPDATE xwiki_entities SET page_id=? WHERE entity_name=?",
                         (uuid.uuid5(uuid.NAMESPACE_URL, 'xwiki:' + row[0]).hex, row[0]))
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS xwiki_page_identity ON xwiki_entities(page_id)")
        XWikiSchema._upgrade_fts(conn)
        conn.commit()

    @staticmethod
    def _upgrade_fts(conn: sqlite3.Connection) -> None:
        """Rebuild legacy contentless indexes from persisted source pages."""
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'xwiki_fts'"
        ).fetchone()[0]
        if not re.search(r"\bcontent\s*=\s*(['\"])\1", sql, re.IGNORECASE):
            return
        conn.execute("SAVEPOINT upgrade_fts")
        try:
            conn.execute("DROP TABLE xwiki_fts")
            conn.execute(
                "CREATE VIRTUAL TABLE xwiki_fts USING fts5("
                "document_id UNINDEXED, title, summary, raw_content)"
            )
            documents = conn.execute(
                "SELECT document_id, title, summary FROM xwiki_documents"
            ).fetchall()
            for document in documents:
                pages = conn.execute(
                    "SELECT content FROM xwiki_pages WHERE document_id = ? ORDER BY page_no",
                    (document[0],),
                ).fetchall()
                conn.execute(
                    "INSERT INTO xwiki_fts (document_id, title, summary, raw_content) "
                    "VALUES (?, ?, ?, ?)",
                    (*document, "\n\n".join(page[0] for page in pages)),
                )
        except Exception:
            conn.execute("ROLLBACK TO upgrade_fts")
            conn.execute("RELEASE upgrade_fts")
            raise
        conn.execute("RELEASE upgrade_fts")


@dataclass(frozen=True)
class DatabaseConfig:
    path: Path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn


class XWikiDatabase:
    def __init__(self, path: str | Path):
        self.config = DatabaseConfig(Path(path).resolve())

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self.config.connect()
        try:
            yield conn
        finally:
            conn.close()

    def bootstrap(self) -> None:
        with self.connection() as conn:
            XWikiSchema.bootstrap(conn)

    def execute(self, statement: str, params: Tuple | list | None = None):
        with self.connection() as conn:
            cur = conn.execute(statement, params or ())
            rows = cur.fetchall()
            conn.commit()
            return rows
