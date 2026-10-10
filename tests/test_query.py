"""Query API fallback tests."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest


def test_query_fallback(service):
    response = asyncio.run(service.ask("什么是测试文档？"))
    assert response["question"] == "什么是测试文档？"
    assert "未配置 LLM key" in response["answer"]
    assert "evidence" in response


def test_document_evidence_includes_citable_identity(service):
    path = service.workspace.paths.inbox_dir / "report.md"
    path.write_text("quasar evidence", encoding="utf-8")
    asyncio.run(service.ingest_inbox())
    response = asyncio.run(service.ask("quasar"))
    evidence = response["evidence"][0]
    assert evidence["type"] == "document"
    document_id = evidence["document_id"]
    assert document_id == service.query_documents("quasar")[0]["document_id"]
    assert "quasar" in service.searcher.read_pages(document_id, [1])


class AnswerLLM:
    has_credentials = True

    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def complete(self, messages):
        self.calls += 1
        time.sleep(0.05)
        return self.answer


def test_no_evidence_does_not_call_model(service):
    fake = AnswerLLM("不应生成")
    service.llm = fake
    response = asyncio.run(service.ask("unknown"))
    assert fake.calls == 0
    assert response["citation_status"] == "insufficient_evidence"


def test_answer_citations_and_event_loop_responsiveness(service):
    service.workspace.paths.inbox_dir.joinpath("doc.md").write_text("quasar evidence", encoding="utf-8")
    asyncio.run(service.ingest_inbox())
    doc_id = service.query_documents("quasar")[0]["document_id"]
    fake = AnswerLLM(f"结论 [{doc_id} p.1]")
    service.llm = fake

    async def scenario():
        task = asyncio.create_task(service.ask("quasar"))
        await asyncio.sleep(0.01)
        assert not task.done()
        return await task

    response = asyncio.run(scenario())
    assert response["citation_status"] == "valid"
    assert response["source_count"] == 1
    fake.answer = "虚构 [nonexistent p.999]"
    invalid = asyncio.run(service.ask("quasar"))
    assert invalid["citation_status"] == "invalid"
    assert invalid["warnings"]


def test_original_search_runs_even_when_wiki_has_multiple_hits(service):
    service.workspace.paths.inbox_dir.joinpath("doc.md").write_text("quasar evidence", encoding="utf-8")
    asyncio.run(service.ingest_inbox())
    for name in ("quasar概念一", "quasar概念二"):
        service.update_entity(name, "概念", base_version=None, reason="创建")
    response = asyncio.run(service.ask("quasar"))
    assert any(block["type"] == "document" for block in response["evidence"])
    assert response["source_count"] == 1


@pytest.mark.parametrize("suffix", ["1", "P.1", "p 1", "p．1"])
def test_known_explicit_citation_format_is_repaired(service, suffix):
    service.workspace.paths.inbox_dir.joinpath("doc.md").write_text("quasar evidence", encoding="utf-8")
    asyncio.run(service.ingest_inbox())
    document = service.query_documents("quasar")[0]["document_id"]
    service.llm = AnswerLLM(f"结论 [{document} {suffix}]")
    response = asyncio.run(service.ask("quasar"))
    assert response["answer"] == f"结论 [{document} p.1]"
    assert response["citation_status"] == "valid"
    assert response["citation_repairs"] == 1


def test_normalization_never_invents_or_overrides_citations():
    from xwiki.agent.query import normalize_citations

    answer = "无引用；[known 2]；[unknown 1]；[1]；[known 1](https://example.com)"
    assert normalize_citations(answer, {("known", 1)}) == (answer, 0)


def test_valid_citation_cannot_hide_unknown_shorthand(service):
    service.workspace.paths.inbox_dir.joinpath("doc.md").write_text("quasar evidence", encoding="utf-8")
    asyncio.run(service.ingest_inbox())
    document = service.query_documents("quasar")[0]["document_id"]
    service.llm = AnswerLLM(f"结论 [{document} 1] [unknown 2]")
    response = asyncio.run(service.ask("quasar"))
    assert response["citation_status"] == "invalid"
    assert "[unknown 2]" in response["answer"]
