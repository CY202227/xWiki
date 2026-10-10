"""Opt-in live evidence-support evaluation using synthetic gold claims."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def evaluate(dataset):
    from xwiki import XWikiConfig
    from xwiki.llm import XWikiLLM
    from xwiki.maintenance import PageOperation, PlanCitation
    from xwiki.evidence import verify_operation, UnsupportedClaimError

    llm = XWikiLLM(XWikiConfig())
    if not llm.has_credentials:
        raise ValueError("Evidence evaluation requires explicit test provider credentials")
    rows = []
    for case in dataset["cases"]:
        operation = PageOperation(action="create", title="测试条目", summary=case["claim"], body=case["claim"],
                                  reason="证据评测", sources=["synthetic-document"],
                                  citations=[PlanCitation(document_id="synthetic-document", page_no=1, quote=case["quote"])])
        supported = False
        error = None
        valid_verdict = True
        try:
            review = await verify_operation(llm, operation, [case.get("context", case["quote"])])
            supported = True
        except UnsupportedClaimError as exc:
            error = str(exc)
            review = exc.review
        except ValueError as exc:
            error = str(exc)
            valid_verdict = False
            review = None
        except Exception as exc:
            error = f"Provider failure: {type(exc).__name__}"
            valid_verdict = False
            review = None
        passed = supported == case["supported"] and valid_verdict
        rows.append({**case, "accepted": supported, "passed": passed, "error": error, "review": review})
        print(json.dumps({"case": case["id"], "passed": passed}, ensure_ascii=False), flush=True)
    return {"dataset": dataset["name"], "passed": sum(row["passed"] for row in rows), "total": len(rows),
            "false_accepts": sum(row["accepted"] and not row["supported"] for row in rows),
            "false_rejections": sum(not row["accepted"] and row["supported"] for row in rows),
            "cases": rows, "scope": "Synthetic gold claim review; model judgement is fallible and is not a proof of entailment."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--dataset", default="tests/fixtures/evidence_eval.json")
    parser.add_argument("--output", default="data/evaluation/evidence-support.json")
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=True, encoding="utf-8-sig")
    result = asyncio.run(evaluate(json.loads(Path(args.dataset).read_text(encoding="utf-8"))))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}, ensure_ascii=False))
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
