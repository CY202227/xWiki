"""Structural lint smoke tests."""

from __future__ import annotations


def test_structural_lint_runs(service):
    report = service.run_structural_lint()
    assert "orphans" in report
    assert "stale_entities" in report
    assert "missing_pages" in report


def test_orphans_and_dangling_links_are_distinct(service):
    service.update_entity("无来源实体", "待补来源", base_version=None, reason="创建")
    with service.db.connection() as conn:
        conn.execute("INSERT INTO xwiki_entity_links VALUES ('不存在的实体', '不存在的文档')")
        conn.commit()
    report = service.run_structural_lint()
    assert report["orphans"]["items"] == ["无来源实体"]
    assert report["dangling_links"]["count"] == 1
    assert report["citations"]["missing"] == ["无来源实体"]


def test_empty_knowledge_lint_skips_model(service):
    import asyncio
    from xwiki.agent.linter import KnowledgeLinter

    class NoCallLLM:
        has_credentials = True

        def complete(self, **kwargs):
            raise AssertionError("No model call for an empty Wiki")

    linter = KnowledgeLinter(NoCallLLM(), service.db)
    result = asyncio.run(linter.check_contradictions())
    assert result == {"status": "skipped", "reason": "no candidates"}
