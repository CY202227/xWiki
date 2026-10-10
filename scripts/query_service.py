"""CLI entrypoint for querying and inspecting an xWiki workspace."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from xwiki import XWikiConfig, XWikiService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Query and inspect an xWiki workspace."
    )
    parser.add_argument(
        "--workspace",
        default="data/my_kb",
        help="Path to workspace (default: data/my_kb).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON for script-friendly consumption.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Print workspace totals and recent events.")

    docs_parser = subparsers.add_parser(
        "docs", help="Search compiled documents by keyword."
    )
    docs_parser.add_argument("query", help="Document search query.")
    docs_parser.add_argument("--limit", type=int, default=10, help="Limit results.")

    wiki_parser = subparsers.add_parser(
        "wiki", help="Search wiki entities by keyword."
    )
    wiki_parser.add_argument("query", help="Entity search query.")
    wiki_parser.add_argument("--limit", type=int, default=10, help="Limit results.")

    ask_parser = subparsers.add_parser("ask", help="Ask a knowledge question.")
    ask_parser.add_argument("query", help="Question text.")
    ask_parser.add_argument(
        "--backflow",
        action="store_true",
        help="Attach backflow/citation fields if supported by model.",
    )

    log_parser = subparsers.add_parser("log", help="Show recent log file tail.")
    log_parser.add_argument(
        "--lines",
        type=int,
        default=40,
        help="Number of lines to display from the log tail.",
    )
    return parser


def _safe_json(value: str | int | float | bool | None) -> str:
    if isinstance(value, str):
        try:
            return json.dumps(json.loads(value), ensure_ascii=False)
        except (TypeError, ValueError):
            return value
    return json.dumps(value, ensure_ascii=False)


def _format_rows(rows: list[dict[str, object]], compact: bool = False) -> str:
    if not rows:
        return "No records found."
    lines = []
    for idx, item in enumerate(rows, start=1):
        if compact:
            summary = item.get("title", item.get("entity_name", "<no title>"))
            if summary is None:
                summary = "<no title>"
            snippet = (
                item.get("summary")
                or item.get("context_snippet")
                or item.get("wiki_consensus", "")
            )
            if snippet is None:
                snippet = ""
            lines.append(f"{idx}. {summary}")
            if snippet:
                lines.append(f"   {str(snippet)[:220]}")
        else:
            lines.append(f"{idx}. {json.dumps(item, ensure_ascii=False)}")
    return "\n".join(lines)


async def _run() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    service = XWikiService(XWikiConfig(workspace=str(Path(args.workspace))))

    if args.command == "status":
        payload = service.status()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"Workspace: {payload['workspace']}")
            print(
                "Totals: documents={documents}, entities={entities}, events={events}".format(
                    **payload["totals"]
                )
            )
            for event in payload.get("recent", []):
                print(
                    f"- {event['event_type']} | {event['description']} | {event.get('created_at')}"
                )
        return

    if args.command == "docs":
        rows = service.query_documents(args.query, limit=args.limit)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            print(_format_rows(rows, compact=True))
        return

    if args.command == "wiki":
        rows = service.query_wiki(args.query, limit=args.limit)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            normalized = []
            for row in rows:
                new_row = dict(row)
                for key in ("attributes_json", "source_links_json"):
                    if key in new_row:
                        new_row[key] = _safe_json(new_row[key])
                normalized.append(new_row)
            print(_format_rows(normalized, compact=True))
        return

    if args.command == "ask":
        answer = await service.ask(args.query, backflow=args.backflow)
        if args.json:
            print(json.dumps(answer, ensure_ascii=False, indent=2))
        else:
            print(answer.get("answer", ""))
            evidence = answer.get("evidence")
            if isinstance(evidence, list) and evidence:
                print("\nEvidence:")
                for item in evidence:
                    print(f"- {item}")
        return

    if args.command == "log":
        log_file = Path(service.workspace.paths.log_file)
        if not log_file.exists():
            print(f"Log file not found: {log_file}")
            return
        lines = log_file.read_text(encoding="utf-8").splitlines()
        tail = lines[-args.lines :]
        print(f"Log file: {log_file}")
        for line in tail:
            print(line)
        return


if __name__ == "__main__":
    asyncio.run(_run())
