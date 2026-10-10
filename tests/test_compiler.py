"""Compiler fallback path when LLM is unavailable."""

from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace

from xwiki.models import ConsensusLLM, EntityListLLM, SourceCitation


class FakeCompilerLLM:
    has_credentials = True

    def __init__(self):
        self.calls = 0
        self.names = ["概念"]
        self.fail_name = None

    def structured(self, messages, response_model):
        self.calls += 1
        if response_model is EntityListLLM:
            parsed = EntityListLLM(entities=[{"name": name, "domain": "领域"} for name in self.names])
        else:
            text = messages[-1]["content"]
            name = text.split("\n", 1)[0].split(": ", 1)[1]
            if name == self.fail_name:
                raise RuntimeError("model failed")
            document_id, page_no = re.search(r"document_id=([^ ]+) page_no=(\d+)", text).groups()
            parsed = ConsensusLLM(new_consensus=f"{name}定义 [{document_id} p.{page_no}]", key_attributes={"新增": "属性"},
                                  citations=[SourceCitation(document_id=document_id, page_no=int(page_no), quote="原文依据")])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))])


def prepare_compiler(service):
    service.workspace.paths.inbox_dir.joinpath("doc.md").write_text("原文依据", encoding="utf-8")
    asyncio.run(service.ingest_inbox())
    fake = FakeCompilerLLM()
    service.llm = fake
    return fake


def test_compile_no_entities_without_credentials(service):
    service.workspace.paths.inbox_dir.joinpath("a.md").write_text(
        "#A\n内容", encoding="utf-8"
    )
    asyncio.run(service.ingest_inbox())
    summary = asyncio.run(service.compile_knowledge())
    assert summary.operation == "compile_knowledge"
    assert summary.stats["documents_seen"] >= 1


def test_compile_is_incremental_and_keeps_citations(service):
    fake = prepare_compiler(service)
    result = asyncio.run(service.compile_knowledge())
    assert result.stats["created"] == 1
    assert service.searcher.get_entity_evidence("概念")["citations"][0]["valid"]
    calls = fake.calls
    repeated = asyncio.run(service.compile_knowledge())
    assert repeated.stats["skipped"] == 1
    assert fake.calls == calls
    assert len(service.entity_revisions("概念")) == 1
    forced = asyncio.run(service.compile_knowledge(force=True))
    assert forced.stats["updated"] == 1
    assert len(service.entity_revisions("概念")) == 1


def test_compile_failure_is_atomic_and_retryable(service):
    fake = prepare_compiler(service)
    fake.names = ["第一个", "第二个"]
    fake.fail_name = "第二个"
    failed = asyncio.run(service.compile_knowledge())
    assert failed.stats["failed"] == 1
    assert service.status()["totals"]["entities"] == 0
    assert list(service.workspace.paths.entity_dir.iterdir()) == []
    with service.db.connection() as conn:
        assert conn.execute("SELECT status FROM xwiki_compile_state").fetchone()[0] == "failed"
    fake.fail_name = None
    retried = asyncio.run(service.compile_knowledge())
    assert retried.stats["created"] == 2
    assert retried.stats["failed"] == 0


def test_zero_entities_finishes_document_without_repeat(service):
    fake = prepare_compiler(service)
    fake.names = []
    first = asyncio.run(service.compile_knowledge())
    assert first.stats["documents_compiled"] == 1
    second = asyncio.run(service.compile_knowledge())
    assert second.stats["skipped"] == 1


def test_compile_preserves_existing_attributes_and_read_context(service):
    fake = prepare_compiler(service)
    service.update_entity("概念", "旧定义", base_version=None, reason="创建", attributes={"已有": "保留"})
    result = asyncio.run(service.compile_knowledge())
    assert result.stats["updated"] == 1
    attributes = json.loads(service.read_entity("概念")["entity"]["attributes_json"])
    assert attributes == {"已有": "保留", "新增": "属性"}


def test_parallel_compilers_do_not_process_source_twice(service):
    fake = prepare_compiler(service)

    async def scenario():
        return await asyncio.gather(service.compile_knowledge(), service.compile_knowledge())

    results = asyncio.run(scenario())
    assert sum(result.stats["created"] for result in results) == 1
    assert sum(result.stats["skipped"] for result in results) == 1
    assert len(service.entity_revisions("概念")) == 1


def test_source_change_during_generation_rejects_stale_result(service):
    fake = prepare_compiler(service)
    original = fake.structured

    def structured(messages, response_model):
        response = original(messages, response_model)
        if response_model is ConsensusLLM:
            with service.db.connection() as conn:
                conn.execute("UPDATE xwiki_documents SET content_hash='changed-during-generation'")
                conn.commit()
        return response

    fake.structured = structured
    result = asyncio.run(service.compile_knowledge())
    assert result.stats["failed"] == 1
    assert service.status()["totals"]["entities"] == 0
    assert "changed" in result.stats["errors"][0]["error"]
