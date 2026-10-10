"""Opt-in live small-model check with synthetic data and a temporary Wiki."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(update: bool = False) -> dict:
    from xwiki import XWikiConfig, XWikiService
    with tempfile.TemporaryDirectory(prefix="xwiki-live-") as folder:
        service = XWikiService(XWikiConfig(workspace=folder))

        class MeteredLLM:
            def __init__(self, provider):
                self.provider = provider
                self.calls = 0

            def __getattr__(self, name):
                return getattr(self.provider, name)

            def structured(self, *args, **kwargs):
                self.calls += 1
                return self.provider.structured(*args, **kwargs)

        meter = MeteredLLM(service.llm)
        service.llm = meter
        source = service.workspace.paths.inbox_dir / "rainwater.md"
        source.write_text("# 雨水收集系统\n雨水收集系统用于收集屋顶雨水。\n储水箱每季度检查一次。\n", encoding="utf-8")
        first = await service.maintain(limit=1)
        first_calls = meter.calls
        cards = service.page_cards()
        second = await service.maintain(limit=1)
        cooling_calls = meter.calls - first_calls
        citations_valid = bool(cards) and all(citation["valid"] for card in cards
                                             for citation in service.searcher.get_entity_evidence(card["entity_name"])["citations"])
        result = {"first": first, "second_processed": second["processed"], "articles": len(cards),
                "citations_valid": citations_valid,
                "model_calls": {"create": first_calls, "cooling": cooling_calls},
                "ok": first["failed"] == 0 and len(cards) == 1 and citations_valid and second["processed"] == 0 and cooling_calls == 0}
        if update and result["ok"]:
            incoming = service.workspace.paths.inbox_dir / "rainwater-update.md"
            incoming.write_text("# 雨水收集系统维护补充\n雨水收集系统用于收集屋顶雨水。\n储水箱每季度检查一次。\n过滤网每月清理一次。\n", encoding="utf-8")
            before_update = meter.calls
            third = await service.maintain(limit=1)
            result["model_calls"]["update"] = meter.calls - before_update
            updated_cards = service.page_cards()
            article = service.read_page(cards[0]["page_id"])["page"]["body"]
            update_ok = third["failed"] == 0 and third["changed"] == 1 and len(updated_cards) == 1 and "过滤网" in article and "季度" in article
            result.update(update=third, update_ok=update_ok, ok=result["ok"] and update_ok)
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--update", action="store_true", help="Also verify new evidence updates the existing article")
    args = parser.parse_args()
    load_dotenv(args.env_file, override=True, encoding="utf-8-sig")
    result = asyncio.run(run(update=args.update))
    # Avoid printing file paths in the temporary workspace or provider config.
    for item in result["first"].get("results", []):
        for change in item.get("changes", []):
            change.pop("path", None)
    for item in result.get("update", {}).get("results", []):
        for change in item.get("changes", []):
            change.pop("path", None)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
