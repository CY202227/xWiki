"""Gold-plan safety evaluation; deterministic, no provider calls."""
import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def evaluate(dataset):
    from xwiki import XWikiConfig, XWikiService
    from xwiki.maintenance import WikiMaintainer, MaintenancePlan, PageOperation, PlanCitation

    rows = []
    for case in dataset["cases"]:
        with tempfile.TemporaryDirectory(prefix="xwiki-plan-eval-") as folder:
            service = XWikiService(XWikiConfig(workspace=folder, llm_api_key="", llm_base_url=""))
            source = service.workspace.paths.inbox_dir / "rain.md"
            source.write_text(dataset["original"] + "\n过滤网每月清理一次。储水箱每月检查一次。", encoding="utf-8")
            await service.ingest_inbox()
            document = service.query_documents("储水箱")[0]["document_id"]
            citation = {"document_id": document, "page_no": 1, "quote": "储水箱每季度检查一次。"}
            service.update_page("雨水系统", dataset["original"], summary="维护要求", base_version=None,
                                reason="基线", sources=[document], citations=[citation])
            record = service.read_page("雨水系统")
            saved_citation = json.loads(record["entity"]["citations_json"])[0]
            operation = PageOperation(action=case["action"], page_id=record["page"]["id"] if case["action"] == "update" else "",
                                      title="雨水系统" if case["action"] == "update" else "雨水设施维护",
                                      summary="维护要求", body=case["body"], reason="评测计划", sources=[document],
                                      citations=[PlanCitation(**{**citation, "quote": case.get("quote", citation["quote"])})])
            plan = MaintenancePlan(reason="评测计划", operations=[operation])
            state = {"source": None, "records": {record["page"]["id"]: record},
                     "source_versions": {document: saved_citation["content_hash"]}}
            accepted = False
            error = None
            try:
                changes = WikiMaintainer(service)._changes(plan, state)
                service.entities.apply(changes, plan.reason)
                accepted = True
            except ValueError as exc:
                error = str(exc)
            unchanged = service.read_page("雨水系统")["version"] == record["version"]
            passed = accepted == case["allowed"] and (accepted or unchanged)
            if case.get("unchanged"):
                passed = passed and unchanged and len(service.entity_revisions("雨水系统")) == 1
            rows.append({"id": case["id"], "expected_allowed": case["allowed"], "accepted": accepted,
                         "passed": passed, "original_unchanged": unchanged, "error": error})
    return {"dataset": dataset["name"], "passed": sum(row["passed"] for row in rows), "total": len(rows),
            "cases": rows, "scope": "Deterministic write guards with gold plans; not model-generated maintenance quality."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="tests/fixtures/maintenance_eval.json")
    parser.add_argument("--output", default="data/evaluation/maintenance-safety.json")
    args = parser.parse_args()
    result = asyncio.run(evaluate(json.loads(Path(args.dataset).read_text(encoding="utf-8"))))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
