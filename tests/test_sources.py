"""Source changes preserve history and fail closed in current-evidence retrieval."""
import asyncio
import json
import sqlite3

import pytest

from xwiki.entities import WikiConflictError
from xwiki.maintenance import WikiMaintainer, MaintenanceQueue


def source(service, name="original", text="oldsignal is valid evidence"):
    path = service.workspace.paths.raw_dir / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    document = service.converter.parse_file(path)
    asyncio.run(service.indexer.index(document))
    return document


def article(service, document):
    return service.update_entity("oldsignal", "oldsignal is valid evidence", base_version=None, reason="create",
                                 sources=[document.document_id], citations=[{"document_id": document.document_id,
                                 "page_no": 1, "quote": document.pages[0].content}])


def test_withdraw_preserves_history_and_excludes_all_retrieval_paths(service):
    document = source(service)
    original = article(service, document)
    change = service.transition_source(document.document_id, expected_hash=document.content_hash, reason="withdraw")
    assert change["affected_pages"][0]["title"] == "oldsignal"
    assert service.read_entity("oldsignal")["version"] == original["version"]
    assert service.read_page("oldsignal")["evidence_status"] == "review_required"
    assert len(service.entity_revisions("oldsignal")) == 1
    assert service.query_documents("oldsignal") == []
    assert service.query_wiki("oldsignal") == []
    assert service.searcher.document_passages(document.document_id, ["oldsignal"]) == []
    with service.db.connection() as conn:
        assert service.searcher._like(conn, ["oldsignal"], 10) == []
    assert "oldsignal" in service.searcher.read_pages(document.document_id, [1])
    assert document.raw_path.exists()
    assert service.source_history(document.document_id)[0]["status"] == "withdrawn"
    assert not service.searcher.get_entity_evidence("oldsignal")["citations"][0]["valid"]
    assert asyncio.run(service.ask("oldsignal"))["source_count"] == 0
    WikiMaintainer(service).scan()
    task = service.maintenance_tasks()[0]
    assert task["status"] == "review"
    assert not MaintenanceQueue(service.db).claim(task, force=True)
    assert service.run_structural_lint()["citations"]["invalid"]


def test_preview_and_optimistic_guard_do_not_mutate_source(service):
    document = source(service)
    article(service, document)
    service.transition_source(document.document_id, expected_hash=document.content_hash, reason="preview", preview=True)
    assert service.source_history(document.document_id) == []
    assert service.query_documents("oldsignal")
    with pytest.raises(WikiConflictError):
        service.transition_source(document.document_id, expected_hash="wrong", reason="stale")
    assert service.source_history(document.document_id) == []
    service.transition_source(document.document_id, expected_hash=document.content_hash, reason="withdraw")
    with pytest.raises(WikiConflictError):
        service.transition_source(document.document_id, expected_hash=document.content_hash, reason="repeat")
    with pytest.raises(ValueError, match="Inactive"):
        asyncio.run(service.indexer.index(document))
    assert len(service.source_history(document.document_id)) == 1


def test_supersede_requires_active_replacement_and_retains_old_source(service):
    old = source(service)
    article(service, old)
    new = source(service, "replacement", "newsignal is the replacement")
    for replacement in (old.document_id, "missing"):
        with pytest.raises(ValueError, match="Replacement"):
            service.transition_source(old.document_id, expected_hash=old.content_hash, reason="replace", replacement_id=replacement)
    result = service.transition_source(old.document_id, expected_hash=old.content_hash, reason="replace", replacement_id=new.document_id)
    assert result["status"] == "superseded"
    assert service.query_documents("newsignal")[0]["document_id"] == new.document_id
    assert service.query_documents("oldsignal") == []
    assert len(service.list_documents()) == 2
    assert service.searcher.read_pages(old.document_id, [1]) == "--- Page 1 ---\n" + old.pages[0].content
    with pytest.raises(ValueError, match="Unknown source"):
        service.update_entity("other", "oldsignal", base_version=None, reason="invalid", sources=[old.document_id])


def test_reindex_snapshots_old_pages_and_marks_articles_for_review(service):
    old = source(service)
    article(service, old)
    old.raw_path.write_text("newsignal is current evidence", encoding="utf-8")
    changed = service.converter.parse_file(old.raw_path)
    asyncio.run(service.indexer.index(changed))
    asyncio.run(service.indexer.index(changed))
    versions = service.source_versions(old.document_id)
    assert len(versions) == 1
    assert versions[0]["content_hash"] == old.content_hash
    assert versions[0]["pages"][0]["content"] == old.pages[0].content
    assert service.source_history(old.document_id)[0]["status"] == "updated"
    assert service.query_wiki("oldsignal") == []
    assert service.query_documents("newsignal")
    assert service.maintenance_tasks()[0]["status"] == "review"
    assert service.read_page("oldsignal")["evidence_status"] == "review_required"


def test_transition_rolls_back_if_task_write_fails(service):
    document = source(service)
    article(service, document)
    with service.db.connection() as conn:
        conn.execute("CREATE TRIGGER prevent_review BEFORE INSERT ON xwiki_maintenance_tasks BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        service.transition_source(document.document_id, expected_hash=document.content_hash, reason="withdraw")
    assert service.source_history(document.document_id) == []
    assert service.query_documents("oldsignal")
    assert service.searcher.get_entity_evidence("oldsignal")["citations"][0]["valid"]


def test_manual_evidence_repair_restores_article_retrieval(service):
    old = source(service)
    article(service, old)
    new = source(service, "replacement", "newsignal is the replacement")
    service.transition_source(old.document_id, expected_hash=old.content_hash, reason="replace", replacement_id=new.document_id)
    page = service.read_entity("oldsignal")
    service.update_entity("oldsignal", "newsignal is the replacement", base_version=page["version"], reason="Reconcile with active source",
                          sources=[new.document_id], citations=[{"document_id": new.document_id, "page_no": 1, "quote": new.pages[0].content}])
    assert service.query_wiki("oldsignal")
    assert service.read_page("oldsignal")["evidence_status"] == "valid"
    WikiMaintainer(service).scan()
    assert service.maintenance_tasks()[0]["status"] == "pending"


def test_legacy_article_without_citations_is_not_used_after_source_update(service):
    old = source(service)
    service.update_entity("oldsignal", "oldsignal is valid evidence", base_version=None, reason="legacy", sources=[old.document_id])
    old.raw_path.write_text("newsignal", encoding="utf-8")
    asyncio.run(service.indexer.index(service.converter.parse_file(old.raw_path)))
    assert service.query_wiki("oldsignal") == []
    assert service.read_page("oldsignal")["evidence_status"] == "review_required"


def test_cli_preview_and_history(service, capsys):
    from xwiki.__main__ import main
    document = source(service)
    args = ["--workspace", str(service.workspace.paths.root)]
    assert main([*args, "transition-source", document.document_id, "--expected-hash", document.content_hash,
                 "--reason", "preview", "--preview"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["preview"]
    assert main([*args, "source-history", document.document_id]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == []


def test_invalid_top_results_do_not_hide_valid_articles(service):
    old = source(service)
    for number in range(21):
        service.update_entity(f"oldsignal-a{number:02}", "oldsignal", base_version=None, reason="legacy", sources=[old.document_id])
    old.raw_path.write_text("newsignal", encoding="utf-8")
    asyncio.run(service.indexer.index(service.converter.parse_file(old.raw_path)))
    new = source(service, "current", "oldsignal is current")
    service.update_entity("oldsignal-z", "oldsignal", base_version=None, reason="current", sources=[new.document_id],
                          citations=[{"document_id": new.document_id, "page_no": 1, "quote": new.pages[0].content}])
    assert [hit["entity_name"] for hit in service.query_wiki("oldsignal", limit=1)] == ["oldsignal-z"]


def test_delete_clears_current_index_preserves_audit_and_invalidates_task_owner(service):
    document = source(service)
    original = article(service, document)
    queue = MaintenanceQueue(service.db)
    queue.enqueue("page", service.read_page("oldsignal")["page"]["id"], original["version"])
    task = queue.list()[0]
    token = queue.claim(task, force=True)
    assert token
    service.delete_source(document.document_id, expected_hash=document.content_hash, reason="obsolete", preview=True)
    assert service.query_documents("oldsignal") and service.source_versions(document.document_id) == []
    result = service.delete_source(document.document_id, expected_hash=document.content_hash, reason="obsolete")
    assert result["status"] == "deleted" and document.raw_path.exists()
    assert service.query_documents("oldsignal") == [] and service.query_wiki("oldsignal") == []
    assert service.read_page("oldsignal")["evidence_status"] == "review_required"
    assert service.read_entity("oldsignal")["version"] == original["version"]
    assert service.source_versions(document.document_id)[0]["pages"][0]["content"] == document.pages[0].content
    assert service.list_documents("deleted")[0]["document_id"] == document.document_id
    with pytest.raises(ValueError, match="do not exist"):
        service.searcher.read_pages(document.document_id, [1])
    with service.db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM xwiki_fts WHERE document_id=?", (document.document_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT status FROM xwiki_compile_state WHERE document_id=?", (document.document_id,)).fetchone()[0] == "deleted"
    queue.finish(task, token, None, done=True)
    assert queue.list()[0]["status"] == "review"
    WikiMaintainer(service).scan()
    assert not queue.claim(queue.list()[0], force=True)
    with pytest.raises(WikiConflictError):
        service.delete_source(document.document_id, expected_hash=document.content_hash, reason="repeat")
    with pytest.raises(ValueError, match="Inactive"):
        asyncio.run(service.indexer.index_all([document]))


def test_delete_rolls_back_snapshot_and_index_when_review_fails(service):
    document = source(service)
    article(service, document)
    with service.db.connection() as conn:
        conn.execute("CREATE TRIGGER prevent_delete_review BEFORE INSERT ON xwiki_maintenance_tasks BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        service.delete_source(document.document_id, expected_hash=document.content_hash, reason="obsolete")
    assert service.source_versions(document.document_id) == []
    assert service.source_history(document.document_id) == []
    assert service.query_documents("oldsignal") and service.query_wiki("oldsignal")


def test_update_source_preserves_identity_archives_and_avoids_stale_citations(service):
    old = source(service)
    article(service, old)
    path = service.workspace.paths.inbox_dir / "new.md"
    path.write_text("newsignal is current evidence", encoding="utf-8")
    preview = asyncio.run(service.update_source(old.document_id, path, expected_hash=old.content_hash, reason="new rules", preview=True))
    assert preview["preview"] and path.exists() and service.source_versions(old.document_id) == []
    result = asyncio.run(service.update_source(old.document_id, path, expected_hash=old.content_hash, reason="new rules"))
    assert result["document_id"] == old.document_id and not path.exists()
    assert old.raw_path.read_text(encoding="utf-8") == old.raw_text
    assert len(service.list_documents()) == 1
    assert service.query_documents("oldsignal") == []
    assert service.query_documents("newsignal")[0]["document_id"] == old.document_id
    assert service.query_wiki("oldsignal") == []
    assert service.source_history(old.document_id)[0]["reason"] == "new rules"
    assert service.source_versions(old.document_id)[0]["pages"][0]["content"] == old.raw_text
    path.write_text("thirdsignal", encoding="utf-8")
    with pytest.raises(WikiConflictError):
        asyncio.run(service.update_source(old.document_id, path, expected_hash=old.content_hash, reason="stale"))
    assert path.exists() and len(service.source_versions(old.document_id)) == 1


def test_update_conflict_during_model_work_keeps_input_and_current_source(service, monkeypatch):
    old = source(service)
    path = service.workspace.paths.inbox_dir / "new.md"
    path.write_text("newsignal", encoding="utf-8")
    original = service.indexer._meta_and_outline

    async def withdraw_during_processing(*args):
        result = await original(*args)
        service.transition_source(old.document_id, expected_hash=old.content_hash, reason="concurrent withdrawal")
        return result

    monkeypatch.setattr(service.indexer, "_meta_and_outline", withdraw_during_processing)
    with pytest.raises(ValueError, match="Inactive"):
        asyncio.run(service.update_source(old.document_id, path, expected_hash=old.content_hash, reason="new rules"))
    assert path.exists() and service.source_versions(old.document_id) == []
    assert service.list_documents("withdrawn") and service.query_documents("newsignal") == []


@pytest.mark.parametrize("delete", [False, True])
def test_inactive_duplicate_is_preserved_and_not_sent_to_maintenance_model(service, monkeypatch, delete):
    old = source(service)
    operation = service.delete_source if delete else service.transition_source
    operation(old.document_id, expected_hash=old.content_hash, reason="obsolete")
    path = service.workspace.paths.inbox_dir / "renamed.md"
    path.write_text(old.raw_text, encoding="utf-8")
    result = asyncio.run(service.ingest_inbox())
    assert result.stats["failed"] == 1 and path.exists()
    maintainer = WikiMaintainer(service)
    maintainer.scan()

    async def forbidden(*args):
        pytest.fail("Inactive evidence must be rejected before any model call")

    monkeypatch.setattr(maintainer, "_structured", forbidden)
    with pytest.raises(ValueError, match="Inactive"):
        asyncio.run(maintainer.plan(maintainer.queue.list()[0]))


def test_active_dedup_and_historical_content_do_not_create_new_sources(service):
    old = source(service)
    path = service.workspace.paths.inbox_dir / "duplicate.md"
    path.write_text(old.raw_text, encoding="utf-8")
    assert asyncio.run(service.ingest_inbox()).stats["skipped"] == 1
    assert not path.exists() and len(service.list_documents()) == 1
    path.write_text("newsignal", encoding="utf-8")
    asyncio.run(service.update_source(old.document_id, path, expected_hash=old.content_hash, reason="new rules"))
    path.write_text(old.raw_text, encoding="utf-8")
    assert asyncio.run(service.ingest_inbox()).stats["failed"] == 1
    assert path.exists() and len(service.list_documents()) == 1


def test_delete_cli_and_update_cli_preview(service, capsys):
    from xwiki.__main__ import main
    old = source(service)
    path = service.workspace.paths.inbox_dir / "new.md"
    path.write_text("newsignal", encoding="utf-8")
    args = ["--workspace", str(service.workspace.paths.root)]
    assert main([*args, "update-source", old.document_id, "--input", str(path), "--expected-hash", old.content_hash,
                 "--reason", "new rules", "--preview"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["preview"]
    assert main([*args, "delete-source", old.document_id, "--expected-hash", old.content_hash, "--reason", "obsolete"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["status"] == "deleted"


def test_mixed_source_article_pauses_on_delete_then_recovers_with_explicit_repair(service):
    old = source(service)
    current = source(service, "current", "newsignal remains supported")
    service.update_entity("mixed", "oldsignal and newsignal", base_version=None, reason="create", sources=[old.document_id, current.document_id],
                          citations=[{"document_id": d.document_id, "page_no": 1, "quote": d.raw_text} for d in [old, current]])
    service.delete_source(old.document_id, expected_hash=old.content_hash, reason="obsolete")
    assert service.query_wiki("newsignal") == []
    assert service.query_documents("newsignal")
    record = service.read_entity("mixed")
    service.update_entity("mixed", current.raw_text, base_version=record["version"], reason="Remove obsolete claim after explicit review",
                          sources=[current.document_id], citations=[{"document_id": current.document_id, "page_no": 1, "quote": current.raw_text}])
    assert service.query_wiki("newsignal") and service.read_page("mixed")["evidence_status"] == "valid"
    WikiMaintainer(service).scan()
    assert service.maintenance_tasks()[0]["status"] == "pending"


def test_update_rejects_duplicate_and_outside_inbox_without_consuming_input(service):
    old = source(service)
    other = source(service, "other", "newsignal")
    path = service.workspace.paths.inbox_dir / "new.md"
    path.write_text(other.raw_text, encoding="utf-8")
    with pytest.raises(ValueError, match="another source"):
        asyncio.run(service.update_source(old.document_id, path, expected_hash=old.content_hash, reason="duplicate"))
    with pytest.raises(ValueError, match="inbox"):
        asyncio.run(service.update_source(old.document_id, other.raw_path, expected_hash=old.content_hash, reason="outside"))
    assert path.exists() and service.source_versions(old.document_id) == []


def test_update_transaction_failure_preserves_current_index_and_inbox(service):
    old = source(service)
    article(service, old)
    path = service.workspace.paths.inbox_dir / "new.md"
    path.write_text("newsignal", encoding="utf-8")
    with service.db.connection() as conn:
        conn.execute("CREATE TRIGGER prevent_update_review BEFORE INSERT ON xwiki_maintenance_tasks BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        asyncio.run(service.update_source(old.document_id, path, expected_hash=old.content_hash, reason="new rules"))
    assert path.exists() and service.query_documents("oldsignal") and service.query_wiki("oldsignal")
    assert service.source_versions(old.document_id) == [] and service.source_history(old.document_id) == []


def test_update_hash_is_rechecked_after_concurrent_update(service, monkeypatch):
    old = source(service)
    first = service.workspace.paths.inbox_dir / "first.md"
    second = service.workspace.paths.inbox_dir / "second.md"
    first.write_text("firstsignal", encoding="utf-8")
    second.write_text("secondsignal", encoding="utf-8")
    original = service.indexer._meta_and_outline
    concurrent = False

    async def update_during_processing(*args):
        nonlocal concurrent
        result = await original(*args)
        if not concurrent:
            concurrent = True
            await service.update_source(old.document_id, second, expected_hash=old.content_hash, reason="concurrent update")
        return result

    monkeypatch.setattr(service.indexer, "_meta_and_outline", update_during_processing)
    with pytest.raises(WikiConflictError):
        asyncio.run(service.update_source(old.document_id, first, expected_hash=old.content_hash, reason="stale update"))
    assert first.exists() and not second.exists()
    assert service.query_documents("secondsignal") and service.query_documents("firstsignal") == []
    assert len(service.source_versions(old.document_id)) == 1


def test_duplicate_is_rechecked_inside_ingestion_transaction(service, monkeypatch):
    from xwiki.indexer import SourceIndexer
    path = service.workspace.paths.inbox_dir / "incoming.md"
    path.write_text("racesignal", encoding="utf-8")
    original = service.indexer._meta_and_outline

    async def competing_ingestion(*args):
        result = await original(*args)
        competing = service.workspace.paths.raw_dir / "competing.md"
        competing.write_text("racesignal", encoding="utf-8")
        indexer = SourceIndexer(service.converter, service.db, service.llm, service.state, service.config)
        await indexer.index(service.converter.parse_file(competing), reject_duplicate=True)
        return result

    monkeypatch.setattr(service.indexer, "_meta_and_outline", competing_ingestion)
    result = asyncio.run(service.ingest_inbox())
    assert result.stats["failed"] == 1 and path.exists()
    assert len(service.list_documents()) == 1
    assert len(service.query_documents("racesignal")) == 1
