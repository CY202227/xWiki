"""Continuous scheduling/write evaluation with a scripted planner, not LLM accuracy."""
import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ScenarioPlanner:
    has_credentials = True

    def __init__(self):
        self.calls = 0
        self.source_calls = 0
        self.mode = "append"
        self.fail_once = False

    def structured(self, messages, response_model):
        from xwiki.maintenance import ReadPlan, MaintenancePlan, PageOperation, PlanCitation
        from xwiki.evidence import EvidenceReview, ClaimDecision
        self.calls += 1
        if self.fail_once:
            self.fail_once = False
            raise TimeoutError("synthetic transient failure")
        payload = json.loads(messages[-1]["content"])
        if response_model is EvidenceReview:
            value = EvidenceReview(decisions=[ClaimDecision(claim_id=claim["id"], supported=True,
                                   evidence_ids=claim["evidence_ids"], reason="模拟证据审查") for claim in payload["claims"]])
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=value))])
        if payload["task"]["kind"] == "source":
            self.source_calls += 1
        if response_model is ReadPlan:
            value = ReadPlan(page_ids=[card["id"] for card in payload["cards"][:1]])
        elif not payload["task"].get("source"):
            value = MaintenancePlan(reason="稳定文章无需修改", operations=[])
        else:
            source = payload["task"]["source"]
            previous = payload["pages"][0] if payload["pages"] else None
            old_body = previous["page"]["body"] if previous else ""
            quote = source["pages"][0]["content"].strip()
            old_citations = [PlanCitation(document_id=c["document_id"], page_no=c["page_no"], quote=c["quote"])
                             for c in previous["citations"] if c["valid"]] if previous else []
            citations = old_citations + [PlanCitation(document_id=source["document_id"], page_no=1, quote=quote)]
            body = quote if self.mode == "unsafe" else old_body + ("\n" if old_body else "") + quote
            value = MaintenancePlan(reason="连续评测更新", operations=[PageOperation(
                action="update" if previous else "create", page_id=previous["page"]["id"] if previous else "",
                title=previous["page"]["title"] if previous else "雨水系统", summary="雨水设施维护", body=body,
                reason="补充资料", sources=list(dict.fromkeys(c.document_id for c in citations)), citations=citations)])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=value))])


async def evaluate():
    from xwiki import XWikiConfig, XWikiService
    with tempfile.TemporaryDirectory(prefix="xwiki-continuous-") as folder:
        service = XWikiService(XWikiConfig(workspace=folder, llm_api_key="", llm_base_url=""))
        planner = ScenarioPlanner()
        service.llm = planner
        rows = []
        protected = []

        async def tick(name, text=None, mode="append", fail=False, expect="success", force=False):
            planner.mode, planner.fail_once = mode, fail
            if text is not None:
                (service.workspace.paths.inbox_dir / "input.md").write_text(text, encoding="utf-8")
            before = planner.calls
            before_source = planner.source_calls
            outcome = await service.maintain(limit=10, force=force)
            body = service.read_page("雨水系统")["page"]["body"] if service.page_cards() else ""
            kept = all(fact in body for fact in protected)
            calls = planner.calls - before
            passed = kept and len(service.page_cards()) <= 1
            if expect == "success":
                passed = passed and outcome["failed"] == 0
            elif expect == "blocked":
                passed = passed and outcome["failed"] == 1 and any(t["status"] == "review" for t in service.maintenance_tasks())
            elif expect == "idle":
                passed = passed and calls == 0 and outcome["processed"] == 0
            elif expect == "review_idle":
                passed = passed and planner.source_calls == before_source and outcome["failed"] == 0
            elif expect == "retry":
                passed = passed and outcome["failed"] == 1 and any(t["status"] == "failed" for t in service.maintenance_tasks())
            if text is not None and expect == "success":
                protected.append(text)
                passed = passed and text in body
            rows.append({"round": len(rows) + 1, "scenario": name, "passed": passed, "model_method_calls": calls,
                         "source_model_method_calls": planner.source_calls - before_source,
                         "facts_retained": kept, "outcome": {k: outcome[k] for k in ("processed", "changed", "failed")}})

        await tick("create", "储水箱每季度检查一次。雨水仅用于灌溉，不得饮用。")
        for fact in ["过滤网每月清理一次。", "检查前必须关闭进水阀门。", "每次检查都应记录日期和操作人员。"]:
            await tick("supplement", fact)
        await tick("unsafe_replacement", "储水箱每天检查一次。", mode="unsafe", expect="blocked")
        for _ in range(6):
            await tick("review_skipped_even_when_forced", expect="review_idle", force=True)
        await tick("changed_input_releases_review", "新的维修记录须保留一年。")
        await tick("transient_timeout", "检修工具必须保持干燥。", fail=True, expect="retry")
        await tick("retry_cooling", expect="idle")
        await tick("transient_recovery", force=True)
        protected.append("检修工具必须保持干燥。")
        for _ in range(10):
            await tick("stable_review_no_revision_growth", force=True)
        revisions = len(service.entity_revisions("雨水系统"))
        return {"rounds": len(rows), "passed": sum(r["passed"] for r in rows), "articles": len(service.page_cards()),
                "revisions": revisions, "expected_revisions": 6, "revision_growth_ok": revisions == 6,
                "model_method_calls": planner.calls, "cases": rows,
                "scope": "Scripted planner; continuous scheduling, recovery and write integrity, not real-model quality."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/evaluation/continuous-maintenance.json")
    args = parser.parse_args()
    result = asyncio.run(evaluate())
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}, ensure_ascii=False))
    return 0 if result["passed"] == result["rounds"] and result["revision_growth_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
