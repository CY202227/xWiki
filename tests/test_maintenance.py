"""Wiki article plans, backward compatibility, and physical cooling semantics."""

import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from xwiki.maintenance import MaintenancePlan, PageOperation, PlanCitation, ReadPlan, MaintenanceQueue, now
from xwiki.models import SourceCitation


class Planner:
    has_credentials = True

    def __init__(self, skip=False):
        self.calls = 0
        self.skip = skip
        self.invalid = False

    def structured(self, messages, response_model):
        self.calls += 1
        from xwiki.evidence import EvidenceReview, ClaimDecision
        if response_model is EvidenceReview:
            payload = json.loads(messages[-1]["content"])
            result = EvidenceReview(decisions=[ClaimDecision(claim_id=claim["id"], supported=True,
                                    evidence_ids=claim["evidence_ids"], reason="模拟审查：证据支持") for claim in payload["claims"]])
        elif response_model is ReadPlan:
            cards = json.loads(messages[-1]["content"])["cards"]
            result = ReadPlan(page_ids=[card["id"] for card in cards[:1]])
        elif self.skip:
            result = MaintenancePlan(retain_source=False, reason="无需入库", operations=[])
        else:
            payload = json.loads(messages[-1]["content"])
            source = payload["task"].get("source")
            if source:
                pages = payload["pages"]
                result = MaintenancePlan(reason="整理资料", operations=[PageOperation(
                    action="update" if pages else "create", page_id=pages[0]["page"]["id"] if pages else "",
                    title=pages[0]["page"]["title"] if pages else "雨水收集", summary="屋顶雨水的收集与维护", body="## 用途\n收集屋顶雨水。\n## 维护\n每季度检查储水箱。", reason="整理来源为文章",
                    sources=[source["document_id"]], citations=[PlanCitation(document_id=source["document_id"], page_no=1,
                    quote="伪造引用" if self.invalid else "收集屋顶雨水。每季度检查储水箱。")])])
            else:
                result = MaintenancePlan(reason="内容稳定，无需改写", operations=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=result))])


def prepare(service, skip=False):
    source = service.workspace.paths.inbox_dir / "rain.md"
    source.write_text("# 雨水收集\n收集屋顶雨水。每季度检查储水箱。", encoding="utf-8")
    service.llm = Planner(skip=skip)
    return source


def test_completed_history_and_active_claims_do_not_hide_due_tasks(service):
    queue = MaintenanceQueue(service.db)
    for index in range(105):
        queue.enqueue("source", f"old-{index}", "hash")
    with service.db.connection() as conn:
        conn.execute("UPDATE xwiki_maintenance_tasks SET status='done'")
        conn.commit()
    queue.enqueue("source", "busy", "hash")
    busy = queue.due(1)[0]
    assert queue.claim(busy)
    queue.enqueue("source", "new", "hash")
    assert [task["subject"] for task in queue.due(1)] == ["new"]
    assert [task["subject"] for task in queue.due(1, force=True)] == ["new"]


def test_article_renderer_has_one_title_and_no_empty_attributes():
    from xwiki.renderer import render_entity_markdown

    markdown = render_entity_markdown({"entity_name": "文章", "page_id": "id", "body": "# 文章\n\n## 内容\n正文"})
    assert markdown.count("# 文章\n") == 1
    assert "## 内容" in markdown
    assert "## 关键属性" not in markdown


def test_full_article_cards_links_and_rollback(service):
    first = service.update_page("方法", "## 步骤\n先检查。", summary="检查流程", base_version=None, reason="创建")
    page = service.read_page("方法")
    assert page["page"]["body"].startswith("## 步骤")
    assert page["page"]["id"]
    second = service.update_page("相关方法", "关联检查流程", summary="相关方法", base_version=None, reason="创建", related=[page["page"]["id"]])
    other = service.read_page("相关方法")
    assert service.page_links(page["page"]["id"])["incoming"] == [other["page"]["id"]]
    assert service.page_cards()[0]["summary"]
    assert service.query_wiki("先检查")[0]["entity_name"] == "方法"
    service.update_entity("方法", "旧接口补充", base_version=first["version"], reason="兼容更新")
    assert service.read_page("方法")["page"]["body"] == "## 步骤\n先检查。"


def test_plan_preview_does_not_archive_or_write_article(service):
    path = prepare(service)
    result = asyncio.run(service.maintain(limit=1, preview=True))
    assert result["failed"] == 0, result["results"]
    assert result["results"][0]["plan"]["operations"]
    assert path.exists()
    assert service.status()["totals"]["documents"] == 0
    assert service.page_cards() == []
    assert list(service.workspace.paths.raw_dir.iterdir()) == []


def test_invalid_page_selection_gets_one_bounded_correction(service):
    prepare(service)
    service.update_page("雨水收集", "## 用途\n收集屋顶雨水。\n## 维护\n每季度检查储水箱。",
                        summary="雨水维护", base_version=None, reason="基线")

    class CorrectablePlanner(Planner):
        def __init__(self):
            super().__init__()
            self.selections = 0

        def structured(self, messages, response_model):
            if response_model is ReadPlan:
                self.selections += 1
                cards = json.loads(messages[1]["content"])["cards"]
                ids = ["invented-id"] if self.selections == 1 else [cards[0]["id"]]
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=ReadPlan(page_ids=ids)))])
            return super().structured(messages, response_model)

    planner = CorrectablePlanner()
    service.llm = planner
    result = asyncio.run(service.maintain(limit=1, preview=True))
    assert result["failed"] == 0, result
    assert planner.selections == 2


def test_repeated_invalid_page_selection_remains_blocked(service):
    path = prepare(service)
    service.update_page("雨水收集", "雨水维护事实", summary="雨水", base_version=None, reason="基线")

    class InvalidPlanner(Planner):
        def structured(self, messages, response_model):
            if response_model is ReadPlan:
                self.calls += 1
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=ReadPlan(page_ids=["invented-id"])))])
            return super().structured(messages, response_model)

    planner = InvalidPlanner()
    service.llm = planner
    result = asyncio.run(service.maintain(limit=1))
    assert result["failed"] == 1
    assert planner.calls == 2
    assert path.exists()


def test_small_model_creates_article_and_cools_without_deletion(service):
    path = prepare(service)
    result = asyncio.run(service.maintain(limit=1))
    assert result["changed"] == 1, result["results"]
    assert not path.exists()
    page = service.read_page("雨水收集")
    assert "## 维护" in page["page"]["body"]
    assert service.searcher.get_entity_evidence("雨水收集")["citations"][0]["valid"]
    calls = service.llm.calls
    assert asyncio.run(service.maintain())["processed"] == 0
    assert service.llm.calls == calls
    result = asyncio.run(service.maintain(force=True))
    assert result["changed"] == 0
    assert len(service.entity_revisions("雨水收集")) == 1
    tasks = service.maintenance_tasks()
    review = next(task for task in tasks if task["kind"] == "page")
    assert review["stability"] == 1
    assert review["status"] == "cooling"
    assert service.page_cards()
    assert list(service.workspace.paths.raw_dir.iterdir())


def test_rejected_input_is_kept_and_changed_content_resets_cooling(service):
    path = prepare(service, skip=True)
    first = asyncio.run(service.maintain(limit=1))
    assert first["processed"] == 1
    assert path.exists()
    assert service.status()["totals"]["documents"] == 0
    calls = service.llm.calls
    assert asyncio.run(service.maintain())["processed"] == 0
    assert calls == service.llm.calls
    path.write_text("更新后的资料", encoding="utf-8")
    assert asyncio.run(service.maintain())["processed"] == 1
    assert path.exists()


def test_invalid_quote_is_rejected_before_archiving(service):
    path = prepare(service)
    service.llm.invalid = True
    result = asyncio.run(service.maintain(limit=1))
    assert result["failed"] == 1
    assert path.exists()
    assert service.page_cards() == []
    assert list(service.workspace.paths.raw_dir.iterdir()) == []


def test_queue_claims_are_exclusive_and_new_evidence_invalidates_old_claim(service):
    queue = MaintenanceQueue(service.db)
    queue.enqueue("source", "doc.md", "v1")
    task = queue.list()[0]
    token = queue.claim(task)
    assert token
    assert queue.claim(task, force=True) is None
    queue.enqueue("source", "doc.md", "v2")
    queue.finish(task, token, MaintenancePlan(reason="旧计划", operations=[]), done=True)
    current = queue.list()[0]
    assert current["fingerprint"] == "v2"
    assert current["status"] == "pending"


def test_review_keeps_proposal_and_requires_explicit_retry(service):
    path = prepare(service)
    service.llm.invalid = True
    result = asyncio.run(service.maintain(limit=1))
    assert result["results"][0]["requires_review"]
    task = service.maintenance_tasks()[0]
    assert task["status"] == "review"
    assert json.loads(task["plan_json"])["operations"]
    calls = service.llm.calls
    assert asyncio.run(service.maintain(force=True))["processed"] == 0
    assert calls == service.llm.calls
    with pytest.raises(ValueError, match="fingerprint"):
        service.retry_maintenance_task(task["id"], "outdated")
    service.llm.invalid = False
    service.retry_maintenance_task(task["id"], task["fingerprint"])
    assert asyncio.run(service.maintain(limit=1))["changed"] == 1
    assert not path.exists()


def test_transient_failures_back_off_then_stop_after_three_attempts(service):
    path = prepare(service)

    class UnavailablePlanner(Planner):
        def structured(self, messages, response_model):
            self.calls += 1
            raise TimeoutError("temporary outage")

    service.llm = UnavailablePlanner()
    dues = []
    for attempt in range(1, 4):
        assert asyncio.run(service.maintain(limit=1, force=True))["failed"] == 1
        task = service.maintenance_tasks()[0]
        assert task["failure_count"] == attempt
        assert task["status"] == ("review" if attempt == 3 else "failed")
        dues.append(task["next_due"])
        assert asyncio.run(service.maintain(limit=1))["processed"] == 0
    assert dues == sorted(dues)
    assert service.llm.calls == 3
    assert asyncio.run(service.maintain(force=True))["failed"] == 0
    assert service.llm.calls == 3
    path.write_text("来源已更正。", encoding="utf-8")
    service.llm = Planner(skip=True)
    assert asyncio.run(service.maintain(limit=1))["processed"] == 1
    assert service.maintenance_tasks()[0]["failure_count"] == 0


def test_broken_related_page_is_rejected(service):
    with pytest.raises(ValueError, match="Related"):
        service.update_page("页面", "正文", summary="摘要", base_version=None, reason="创建", related=["missing"])


def test_identical_article_update_does_not_expand_revisions(service):
    created = service.update_page("页面", "正文", summary="摘要", base_version=None, reason="创建")
    repeated = service.update_page("页面", "正文", summary="摘要", base_version=created["version"], reason="重复检查")
    assert not repeated["changed"]
    assert repeated["version"] == created["version"]
    assert len(service.entity_revisions("页面")) == 1


def test_legacy_revision_restores_legacy_body_after_article_upgrade(service):
    created = service.update_entity("旧实体", "旧定义", base_version=None, reason="创建")
    revision = service.entity_revisions("旧实体")[0]
    snapshot = json.loads(revision["snapshot_json"])
    for key in ("body", "summary", "related_json"):
        snapshot.pop(key)
    with service.db.connection() as conn:
        conn.execute("UPDATE xwiki_entity_revisions SET snapshot_json=? WHERE id=?", (json.dumps(snapshot), revision["id"]))
        conn.commit()
    upgraded = service.update_page("旧实体", "## 新正文", summary="新摘要", base_version=created["version"], reason="升级")
    service.rollback_entity("旧实体", revision["id"], base_version=upgraded["version"], reason="恢复旧版")
    assert service.read_page("旧实体")["page"]["body"] == "旧定义"
