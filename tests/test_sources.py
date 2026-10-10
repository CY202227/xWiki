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
