"""Repeatable gold-answer evaluation; --live explicitly enables provider calls."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def evaluate(dataset: dict, live: bool) -> dict:
    from xwiki import XWikiConfig, XWikiService

    with tempfile.TemporaryDirectory(prefix="xwiki-eval-") as folder:
        offline = XWikiService(XWikiConfig(workspace=folder, llm_api_key="", llm_base_url=""))
        for index, document in enumerate(dataset["documents"]):
            (offline.workspace.paths.inbox_dir / f"source-{index}.md").write_text(
                f"# {document['title']}\n{document['body']}\n", encoding="utf-8")
        await offline.ingest_inbox()
        service = XWikiService(XWikiConfig(workspace=folder)) if live else offline
        if live and not service.llm.has_credentials:
            raise ValueError("Live evaluation requires chat provider credentials")
        rows = []
        for case in dataset["cases"]:
            started = time.monotonic()
            hits = service.query_documents(case["question"], limit=3)
            title_map = {f"source-{index}": document["title"] for index, document in enumerate(dataset["documents"])}
            titles = [title_map.get(hit["title"], hit["title"]) for hit in hits]
            expected = case["titles"]
            relevant = [index + 1 for index, title in enumerate(titles) if title in expected]
            row = {"id": case["id"], "question": case["question"], "retrieved_titles": titles,
                   "expected_titles": expected, "hit_at_3": bool(relevant) if expected else None,
                   "reciprocal_rank": 1 / min(relevant) if relevant else 0 if expected else None}
            if live:
                try:
                    result = await service.ask(case["question"])
                    answer = result["answer"]
                    correct = (result.get("citation_status") == "insufficient_evidence" if case.get("unanswerable")
                               else all(any(term in answer for term in group) for group in case["answer_groups"]))
                    row.update(answer=answer, answer_correct=correct, citation_status=result.get("citation_status"),
                               citation_valid=result.get("citation_status") == "valid" if expected else None)
                except Exception as error:
                    row.update(answer_correct=False, citation_valid=False if expected else None, error=type(error).__name__)
            row["seconds"] = round(time.monotonic() - started, 2)
            rows.append(row)
            print(json.dumps({"case": case["id"], "completed": len(rows)}, ensure_ascii=False), flush=True)
        def metric(key):
            values = [row[key] for row in rows if row.get(key) is not None]
            return {"score": round(sum(values) / len(values), 4), "n": len(values)} if values else None
        return {"dataset": dataset["name"], "live": live, "metrics": {key: metric(key) for key in
                ["hit_at_3", "reciprocal_rank", "answer_correct", "citation_valid"]}, "cases": rows,
                "limitations": "Synthetic small corpus; keyword answer checks, not semantic grading. Citation validity verifies locators, not entailment. No Wiki maintenance score is inferred from this retrieval/QA run."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="tests/fixtures/wiki_eval.json")
    parser.add_argument("--output", default="data/evaluation/latest.json")
    parser.add_argument("--env-file")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=True, encoding="utf-8-sig")
    report = asyncio.run(evaluate(json.loads(Path(args.dataset).read_text(encoding="utf-8-sig")), args.live))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False))


if __name__ == "__main__":
    main()
