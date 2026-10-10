"""Markdown renderers for wiki entities."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

from .workspace import Workspace
from .files import atomic_write


def _slugify(value: str) -> str:
    slug = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip()
    )
    return slug[:120] or "entity"


def render_entity_markdown(entity: dict, report: str | None = None) -> str:
    attrs = json.loads(entity.get("attributes_json", "{}"))
    sources = json.loads(entity.get("source_links_json", "[]"))
    body = entity.get("body") or ""
    if body and body.splitlines()[0].strip() == f"# {entity.get('entity_name', '')}":
        body = "\n".join(body.splitlines()[1:]).lstrip()
    lines = [
        "---",
        "type: xwiki_entity",
        f"title: {json.dumps(entity.get('entity_name', ''), ensure_ascii=False)}",
        f"domain: {json.dumps(entity.get('domain', ''), ensure_ascii=False)}",
        f"updated_at: {json.dumps(entity.get('updated_at', ''), ensure_ascii=False)}",
        "---",
        "",
        f"# {entity.get('entity_name', '')}",
        "",
        body or f"> {entity.get('consensus_summary', '')}",
        "",
        "## 关键属性",
        "",
    ]
    for key, value in attrs.items():
        lines.append(f"- **{key}**: {value}")
    if not attrs and not entity.get("body"):
        lines.append("- 暂无结构化属性")
    elif not attrs:
        del lines[-2:]
    lines.extend(
        [
            "",
            "## 来源文档",
            "",
            *[f"- {item}" for item in sources],
        ],
    )
    if report:
        lines.extend(["", "## 备注", "", report])
    if entity.get("body"):
        lines[1] = "type: xwiki_page"
        lines.insert(2, f"id: {entity['page_id']}")
        related = json.loads(entity.get("related_json", "[]"))
        if related:
            lines.extend(["", "## 相关页面", "", *[f"- [[{page_id}]]" for page_id in related]])
    citations = json.loads(entity.get("citations_json", "[]"))
    if citations:
        lines.extend(["", "## 原文证据", ""])
        for citation in citations:
            lines.append(f"- [{citation['document_id']} p.{citation['page_no']}] {citation['quote']}")
    return "\n".join(lines).strip() + "\n"


def entity_file_name(name: str) -> str:
    # A digest also avoids Windows reserved names and sanitized-name collisions.
    return f"{_slugify(name)[:80]}-{hashlib.sha256(name.encode('utf-8')).hexdigest()[:16]}.md"


def write_entity_file(
    workspace: Workspace, entity: dict, report: str | None = None
) -> Path:
    file_name = entity_file_name(entity['entity_name'])
    target = workspace.paths.entity_dir / file_name
    atomic_write(target, render_entity_markdown(entity, report=report))
    return target
