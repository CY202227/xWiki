"""Version, citation, and filesystem integrity regression tests."""

import asyncio
import json
from pathlib import Path

import pytest

from xwiki.entities import WikiConflictError


def test_preview_versions_and_rollback(service):
    preview = service.update_entity("方法", "原始定义", base_version=None, reason="建立定义", preview=True)
    assert "原始定义" in preview["diff"]
    assert service.searcher.list_entities() == []
    assert list(service.workspace.paths.entity_dir.iterdir()) == []
    created = service.update_entity("方法", "原始定义", base_version=None, reason="建立定义")
    first_revision = service.entity_revisions("方法")[0]["id"]
    updated = service.update_entity("方法", "修正定义", base_version=created["version"], reason="修正")
    with pytest.raises(WikiConflictError):
        service.update_entity("方法", "过期修改", base_version=created["version"], reason="错误")
    service.rollback_entity("方法", first_revision, base_version=updated["version"], reason="恢复原始定义")
    assert service.read_entity("方法")["entity"]["consensus_summary"] == "原始定义"
    assert len(service.entity_revisions("方法")) == 3
    assert service.query_wiki("原始定义")[0]["entity_name"] == "方法"


def test_external_markdown_edit_is_preserved(service):
    created = service.update_entity("概念", "定义", base_version=None, reason="创建")
    path = Path(created["path"])
    path.write_text("人工修改", encoding="utf-8")
    with pytest.raises(WikiConflictError, match="externally"):
        service.update_entity("概念", "模型修改", base_version=created["version"], reason="更新")
    assert path.read_text(encoding="utf-8") == "人工修改"
    assert service.read_entity("概念")["entity"]["consensus_summary"] == "定义"
    assert service.run_structural_lint()["entity_files"]["modified"][0]["entity_name"] == "概念"


def test_filename_collisions_and_windows_names(service):
    paths = []
    for name in ("A/B", "A:B", "CON", "概念: 类型\n第二行"):
        result = service.update_entity(name, "内容", base_version=None, reason="创建")
        paths.append(result["path"])
    assert len(set(paths)) == 4
    for path in paths:
        assert Path(path).parent == service.workspace.paths.entity_dir
    text = Path(paths[-1]).read_text(encoding="utf-8")
    assert 'title: "概念: 类型\\n第二行"' in text


def test_citations_reject_fabricated_quotes_and_detect_source_changes(service):
    path = service.workspace.paths.raw_dir / "source.md"
    path.write_text("<!-- PAGE_1 -->\n真实证据\n<!-- PAGE_2 -->\n第二页", encoding="utf-8")
    document = service.converter.parse_file(path)
    asyncio.run(service.indexer.index(document))
    citation = {"document_id": document.document_id, "page_no": 1, "quote": "虚构证据"}
    with pytest.raises(ValueError, match="quote"):
        service.update_entity("概念", "事实", base_version=None, reason="创建", sources=[document.document_id], citations=[citation])
    citation["quote"] = "真实证据"
    service.update_entity("概念", "事实", base_version=None, reason="创建", sources=[document.document_id], citations=[citation])
    evidence = service.searcher.get_entity_evidence("概念")
    assert evidence["citations"][0]["valid"]
    assert evidence["citations"][0]["content_hash"] == document.content_hash
    path.write_text("变化后的证据", encoding="utf-8")
    asyncio.run(service.indexer.index(service.converter.parse_file(path)))
    assert not service.searcher.get_entity_evidence("概念")["citations"][0]["valid"]
    assert service.run_structural_lint()["citations"]["invalid"]


def test_file_failure_restores_database_files_and_history(service, monkeypatch):
    first = service.update_entity("已有", "旧内容", base_version=None, reason="创建")
    entity = service.read_entity("已有")["entity"]
    entity["consensus_summary"] = "新内容"
    other = {"entity_name": "新增", "domain": "领域", "consensus_summary": "内容", "attributes_json": "{}", "source_links_json": "[]", "citations_json": "[]"}
    from xwiki import entities
    real_write = entities.atomic_write

    def fail_second(path, text):
        if "新增" in path.name:
            raise OSError("disk failure")
        real_write(path, text)

    monkeypatch.setattr(entities, "atomic_write", fail_second)
    with pytest.raises(OSError, match="disk failure"):
        service.entities.apply([{"entity": entity, "base_version": first["version"]}, {"entity": other, "base_version": None}], "批量修改")
    assert service.read_entity("已有")["entity"]["consensus_summary"] == "旧内容"
    assert "旧内容" in Path(first["path"]).read_text(encoding="utf-8")
    with pytest.raises(KeyError):
        service.read_entity("新增")
    assert len(service.entity_revisions("已有")) == 1
