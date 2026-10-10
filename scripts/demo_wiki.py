"""Offline, scripted Wiki walkthrough using only public synthetic sources."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xwiki import XWikiConfig, XWikiService
from xwiki.maintenance import MaintenancePlan, PageOperation, PlanCitation, ReadPlan


class ScriptedMaintainer:
    """Copy source sentences into plans; never make network calls or grade a model."""

    has_credentials = True

    @staticmethod
    def title(source):
        return source["pages"][0]["content"].splitlines()[0].lstrip("# ").strip()

    def structured(self, messages, response_model):
        payload = json.loads(messages[-1]["content"])
        source = payload["task"].get("source")
        if response_model is ReadPlan:
            title = self.title(source) if source else ""
            result = ReadPlan(page_ids=[card["id"] for card in payload["cards"] if card["title"] == title])
        elif response_model is MaintenancePlan:
            if not source:
                result = MaintenancePlan(reason="文章稳定，保持原文并降低维护频率", operations=[])
            else:
                title = self.title(source)
                previous = next((page for page in payload["pages"] if page["page"]["title"] == title), None)
                text = source["pages"][0]["content"]
                sentences = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
                body = "\n".join(f"{line} [{source['document_id']} p.1]" for line in sentences)
                old_citations = previous["citations"] if previous else []
                citations = [PlanCitation(document_id=item["document_id"], page_no=item["page_no"], quote=item["quote"]) for item in old_citations]
                citations.append(PlanCitation(document_id=source["document_id"], page_no=1, quote=text))
                if previous:
                    body = previous["page"]["body"] + "\n\n" + body
                result = MaintenancePlan(reason="将公开演示资料整理为可溯源文章", operations=[PageOperation(
                    action="update" if previous else "create", page_id=previous["page"]["id"] if previous else "",
                    title=title, summary=sentences[-1], body=body, domain="园艺",
                    sources=list(dict.fromkeys(item.document_id for item in citations)), citations=citations,
                    reason="保留已有事实和引用，追加来源原文")])
        else:
            raise ValueError("Demo only supports verbatim plans; unexpected model request")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=result))])


async def run_demo(workspace: Path, sources: Path) -> dict:
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError("Use an empty demo workspace; existing knowledge will not be overwritten")
    service = XWikiService(XWikiConfig(workspace=str(workspace), llm_api_key="", llm_base_url=""))
    service.llm = ScriptedMaintainer()
    stages = []
    for name in ("01-rain.md", "02-compost.md", "03-rain-update.md"):
        target = service.workspace.paths.inbox_dir / name
        target.write_text((sources / name).read_text(encoding="utf-8"), encoding="utf-8")
        result = await service.maintain(limit=10)
        if result["failed"] or result["changed"] != 1:
            raise RuntimeError(f"Demo maintenance failed at {name}: {result}")
        stages.append({"source": name, "maintenance": result})
    page = service.read_page("雨水收集")
    evidence = service.searcher.get_entity_evidence("雨水收集")
    if not evidence["citations"] or not all(item["valid"] for item in evidence["citations"]):
        raise RuntimeError("Demo contains invalid source citations")
    hits = service.query_wiki("雨水收集", limit=3)
    # Query in offline mode: evidence retrieval is not presented as a generated answer.
    service.llm = service.indexer._llm
    answer = await service.ask("雨水收集")
    service.llm = ScriptedMaintainer()
    stable = await service.maintain(limit=10, force=True)
    tasks = service.maintenance_tasks()
    revisions = service.entity_revisions("雨水收集")
    oldest = revisions[-1]
    rollback = service.rollback_entity("雨水收集", oldest["id"], base_version=page["version"], reason="演示回滚至补充规则之前")
    restored = service.read_page("雨水收集")
    if "暴雨后" in restored["page"]["body"] or "暴雨后" not in page["page"]["body"]:
        raise RuntimeError("Demo rollback failed to restore the earlier article")
    return {"mode": "offline-scripted", "model_quality_score": None, "workspace": str(workspace.resolve()),
            "workspace_preserved": True, "stages": stages, "cards": service.page_cards(), "search_hits": hits,
            "retrieved_answer": answer, "verified_citations": evidence["citations"],
            "stable_maintenance": stable, "cooling_tasks": tasks, "revisions_before_rollback": revisions,
            "rollback": rollback, "restored_page": restored["page"], "retained_sources": service.list_documents(),
            "limitations": "Synthetic sources and scripted plans verify the workflow, not real LLM quality. Offline QA returns evidence only."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", help="Empty directory to preserve the demo Wiki; otherwise use temporary storage")
    parser.add_argument("--output", default="data/demo/report.json")
    args = parser.parse_args()
    sources = Path(__file__).resolve().parents[1] / "examples/garden/sources"
    try:
        if args.workspace:
            report = asyncio.run(run_demo(Path(args.workspace), sources))
        else:
            with tempfile.TemporaryDirectory(prefix="xwiki-demo-") as directory:
                report = asyncio.run(run_demo(Path(directory), sources))
                report["workspace_preserved"] = False
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": True, "mode": report["mode"], "report": str(output.resolve())}, ensure_ascii=False))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
