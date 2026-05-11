"""Markdown renderers for wiki entities."""

from __future__ import annotations

import json
from pathlib import Path

from .workspace import Workspace


def _slugify(value: str) -> str:
  slug = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
  return slug[:120] or "entity"


def render_entity_markdown(entity: dict, report: str | None = None) -> str:
  attrs = json.loads(entity.get("attributes_json", "{}"))
  sources = json.loads(entity.get("source_links_json", "[]"))
  lines = [
      "---",
      "type: xwiki_entity",
      f"title: {entity.get('entity_name', '')}",
      f"domain: {entity.get('domain', '')}",
      f"updated_at: {entity.get('updated_at', '')}",
      "---",
      "",
      f"# {entity.get('entity_name', '')}",
      "",
      f"> {entity.get('consensus_summary', '')}",
      "",
      "## 关键属性",
      "",
  ]
  for key, value in attrs.items():
    lines.append(f"- **{key}**: {value}")
  if not attrs:
    lines.append("- 暂无结构化属性")
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
  return "\n".join(lines).strip() + "\n"


def write_entity_file(workspace: Workspace, entity: dict, report: str | None = None) -> Path:
  file_name = f"{_slugify(entity['entity_name'])}.md"
  target = workspace.paths.entity_dir / file_name
  target.write_text(render_entity_markdown(entity, report=report), encoding="utf-8")
  return target
