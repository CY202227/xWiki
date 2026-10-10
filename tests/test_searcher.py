"""Retrieval quality and source evidence regressions."""

import asyncio

import pytest


def test_chinese_question_retrieves_body_beyond_summary(service):
    path = service.workspace.paths.inbox_dir / "report.md"
    path.write_text("前言" * 500 + "碳排放是温室气体排放。", encoding="utf-8")
    asyncio.run(service.ingest_inbox())
    hits = service.query_documents("什么是碳排放？")
    assert len(hits) == 1
    assert "碳排放" in hits[0]["context_snippet"]
    response = asyncio.run(service.ask("什么是碳排放？"))
    assert "碳排放" in response["evidence"][0]["passages"][0]["content"]
    assert response["evidence"][0]["passages"][0]["page_no"] == 1


def test_exact_entity_precedes_recent_incidental_match(service):
    service.update_entity("碳排放", "概念定义", base_version=None, reason="创建")
    service.update_entity("新文章", "讨论碳排放", base_version=None, reason="创建")
    assert service.query_wiki("碳排放")[0]["entity_name"] == "碳排放"
    assert service.query_wiki("   ") == []


@pytest.mark.parametrize("query,limit", [("query", 0), ("query", -1), ("x" * 501, 10)])
def test_search_rejects_unbounded_inputs(service, query, limit):
    with pytest.raises(ValueError):
        service.query_documents(query, limit)
