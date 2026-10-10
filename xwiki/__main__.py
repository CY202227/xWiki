"""JSON CLI for maintenance agents; default invocation is read-only status."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

from .service import XWikiService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read and maintain a versioned Wiki")
    parser.add_argument("--workspace", default="data/my_kb")
    parser.add_argument("--env-file", help="Optional private dotenv file; never included in JSON output")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("status")
    commands.add_parser("ingest")
    compile_parser = commands.add_parser("compile")
    compile_parser.add_argument("--force", action="store_true")
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--kind", choices=("wiki", "documents"), default="wiki")
    search.add_argument("--limit", type=int, default=10)
    listing = commands.add_parser("list")
    listing.add_argument("--domain")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--offset", type=int, default=0)
    sources = commands.add_parser("sources")
    sources.add_argument("--status")
    sources.add_argument("--limit", type=int, default=50)
    sources.add_argument("--offset", type=int, default=0)
    for command in ("read", "revisions"):
        commands.add_parser(command).add_argument("name")
    pages = commands.add_parser("read-source")
    pages.add_argument("document_id")
    pages.add_argument("pages", type=int, nargs="+")
    update = commands.add_parser("update")
    update.add_argument("--input", required=True, help="UTF-8 JSON with name, content, base_version, reason and optional sources/citations")
    update.add_argument("--preview", action="store_true")
    rollback = commands.add_parser("rollback")
    rollback.add_argument("name")
    rollback.add_argument("revision_id", type=int)
    rollback.add_argument("--base-version", required=True)
    rollback.add_argument("--reason", required=True)
    commands.add_parser("lint")
    maintain = commands.add_parser("maintain")
    maintain.add_argument("--limit", type=int, default=2)
    maintain.add_argument("--force", action="store_true")
    maintain.add_argument("--preview", action="store_true")
    commands.add_parser("tasks")
    read_page = commands.add_parser("read-page")
    read_page.add_argument("page")
    write_page = commands.add_parser("write-page")
    write_page.add_argument("--input", required=True)
    write_page.add_argument("--preview", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.env_file:
            from dotenv import load_dotenv
            load_dotenv(args.env_file, override=True, encoding="utf-8-sig")
        service = XWikiService(workspace=args.workspace)
        command = args.command or "status"
        if command == "status":
            result = service.status()
        elif command == "ingest":
            result = asyncio.run(service.ingest_inbox())
        elif command == "compile":
            result = asyncio.run(service.compile_knowledge(force=args.force))
        elif command == "maintain":
            result = asyncio.run(service.maintain(limit=args.limit, force=args.force, preview=args.preview))
        elif command == "tasks":
            result = service.maintenance_tasks()
        elif command == "read-page":
            result = service.read_page(args.page)
        elif command == "write-page":
            payload = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
            result = service.update_page(preview=args.preview, **payload)
        elif command == "search":
            operation = service.query_wiki if args.kind == "wiki" else service.query_documents
            result = operation(args.query, args.limit)
        elif command == "list":
            result = service.searcher.list_entities(args.domain, args.limit, args.offset)
        elif command == "sources":
            result = service.list_documents(args.status, args.limit, args.offset)
        elif command == "read":
            result = service.read_entity(args.name)
        elif command == "read-source":
            result = {"document_id": args.document_id, "content": service.searcher.read_pages(args.document_id, args.pages)}
        elif command == "revisions":
            result = service.entity_revisions(args.name)
        elif command == "update":
            payload = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("Update input must be a JSON object")
            if "base_version" not in payload:
                raise ValueError("base_version is required; use null only when creating a page")
            result = service.update_entity(preview=args.preview, **payload)
        elif command == "rollback":
            result = service.rollback_entity(args.name, args.revision_id, base_version=args.base_version, reason=args.reason)
        else:
            result = service.run_structural_lint()
        if is_dataclass(result):
            result = asdict(result)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        if isinstance(result, dict) and result.get("stats", {}).get("failed"):
            return 1
        if isinstance(result, dict) and result.get("failed"):
            return 1
        return 0
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(json.dumps({"ok": False, "error": {"type": type(error).__name__, "message": str(error)}}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
