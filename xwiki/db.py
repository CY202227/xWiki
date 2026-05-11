"""Database bootstrap and connection helpers."""

from __future__ import annotations

import sqlite3
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
            document_id UNINDEXED, title, summary, raw_content, content=''
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
        ]
        for ddl in schema:
            conn.execute(ddl)
        conn.commit()


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
