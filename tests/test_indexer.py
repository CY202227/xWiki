"""Indexing behavior without LLM credentials."""

from __future__ import annotations

import asyncio
import sqlite3

from xwiki.converter import MarkdownConverter
from xwiki.db import XWikiSchema


def test_indexer_records_rows(service):
    file_path = service.workspace.paths.raw_dir / "one.md"
    file_path.write_text("# doc\n内容\n", encoding="utf-8")
    parsed = MarkdownConverter().parse_file(file_path)
    stats = asyncio.run(service.indexer.index_all([parsed]))
    assert stats["added"] == 1
    overview = service.searcher.get_overview()
    assert overview["totals"]["documents"] == 1


def test_search_returns_source_identity_and_body_snippet(service):
    path = service.workspace.paths.raw_dir / "report.md"
    path.write_text("# Report\n" + "introduction " * 150 + "quasar evidence", encoding="utf-8")
    document = MarkdownConverter().parse_file(path)
    asyncio.run(service.indexer.index(document))

    hits = service.query_documents("quasar")
    assert len(hits) == 1
    assert hits[0]["document_id"] == document.document_id
    assert hits[0]["title"] == document.title
    assert "[quasar]" in hits[0]["context_snippet"]


def test_reindex_replaces_old_search_terms_without_duplicates(service):
    path = service.workspace.paths.raw_dir / "report.md"
    path.write_text("obsoletekeyword", encoding="utf-8")
    asyncio.run(service.indexer.index(MarkdownConverter().parse_file(path)))
    path.write_text("replacementkeyword", encoding="utf-8")
    document = MarkdownConverter().parse_file(path)
    asyncio.run(service.indexer.index(document))
    asyncio.run(service.indexer.index(document))

    assert service.query_documents("obsoletekeyword") == []
    assert len(service.query_documents("replacementkeyword")) == 1
    with service.db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM xwiki_fts").fetchone()[0] == 1


def test_legacy_index_is_rebuilt_from_sources_in_page_order():
    conn = sqlite3.connect(":memory:")
    try:
        XWikiSchema.bootstrap(conn)
        conn.execute(
            "INSERT INTO xwiki_documents "
            "(document_id, source_path, raw_path, title, summary, created_at, updated_at) "
            "VALUES ('doc', 'raw/report.md', 'raw/report.md', 'Report', 'Overview', 'now', 'now')"
        )
        conn.executemany(
            "INSERT INTO xwiki_pages VALUES (?, ?, ?)",
            [("doc", 2, "second quasar"), ("doc", 1, "first")],
        )
        conn.execute("DROP TABLE xwiki_fts")
        conn.execute(
            "CREATE VIRTUAL TABLE xwiki_fts USING fts5("
            "document_id UNINDEXED, title, summary, raw_content, content='')"
        )
        for _ in range(2):
            conn.execute("INSERT INTO xwiki_fts VALUES ('doc', 'Report', 'Overview', 'staleterm')")
        conn.commit()

        XWikiSchema.bootstrap(conn)
        XWikiSchema.bootstrap(conn)

        assert conn.execute(
            "SELECT document_id, title, summary, raw_content FROM xwiki_fts"
        ).fetchall() == [("doc", "Report", "Overview", "first\n\nsecond quasar")]
        hit = conn.execute(
            "SELECT document_id, snippet(xwiki_fts, 3, '[', ']', '...', 40) "
            "FROM xwiki_fts WHERE xwiki_fts MATCH 'quasar'"
        ).fetchone()
        assert hit[0] == "doc"
        assert "[quasar]" in hit[1]
        assert conn.execute("SELECT COUNT(*) FROM xwiki_fts WHERE xwiki_fts MATCH 'staleterm'").fetchone()[0] == 0
    finally:
        conn.close()


def test_schema_upgrades_legacy_compile_state_without_losing_status():
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE xwiki_compile_state (document_id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL, error TEXT, updated_at TEXT NOT NULL)")
        conn.execute("INSERT INTO xwiki_compile_state VALUES ('doc', 'Report', 'failed', 'retry me', 'now')")
        XWikiSchema.bootstrap(conn)
        XWikiSchema.bootstrap(conn)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(xwiki_compile_state)")}
        assert {"content_hash", "compiler_version", "run_id"} <= columns
        assert conn.execute("SELECT status, error FROM xwiki_compile_state").fetchone() == ("failed", "retry me")
    finally:
        conn.close()
