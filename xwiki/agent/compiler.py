"""Knowledge compilation pass that builds entity-level wiki pages."""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, Field

from ..db import XWikiDatabase
from ..llm import XWikiLLM
from ..models import ConsensusLLM, EntityListLLM
from ..renderer import write_entity_file
from ..workspace import Workspace


class KnowledgeCompiler:
  def __init__(
      self,
      db: XWikiDatabase,
      workspace: Workspace,
      llm: XWikiLLM,
      batch_size: int = 4,
  ) -> None:
    self._db = db
    self._workspace = workspace
    self._llm = llm
    self._batch_size = batch_size

  async def _extract_entities(self, title: str, full_text: str, domains: list[str]):
    if not self._llm.has_credentials:
      return []
    resp = self._llm.structured(
        messages=[
            {
                "role": "system",
                "content": (
                    "你是知识抽取专家。提取可复用实体。"
                    "输出 name（实体名）和 domain（领域）。"
                    f"已知领域: {domains}"
                ),
            },
            {"role": "user", "content": f"文档标题: {title}\n文档内容:\n{full_text}"},
        ],
        response_model=EntityListLLM,
    )
    return resp.choices[0].message.parsed.entities

  async def _consensus(self, name: str, domain: str, context: str, previous: str | None):
    if not self._llm.has_credentials:
      return (
          previous or f"{name} 当前暂无充分定义，建议补充原文。",
          {},
      )
    baseline = previous or "尚无定义。"
    resp = self._llm.structured(
        messages=[
            {
                "role": "system",
                "content": (
                    "你是百科式知识整合人，输出稳定、可核验的定义与关键属性。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"实体: {name}\n领域: {domain}\n"
                    f"已有定义: {baseline}\n\n原文参考:\n{context}"
                ),
            },
        ],
        response_model=ConsensusLLM,
    )
    payload = resp.choices[0].message.parsed
    return payload.new_consensus, payload.key_attributes

  async def _compile_document(self, doc_id: str) -> dict[str, int]:
    with self._db.connection() as conn:
      meta = conn.execute(
          "SELECT title, doc_date, summary FROM xwiki_documents WHERE document_id = ?",
          (doc_id,),
      ).fetchone()
      pages = conn.execute(
          "SELECT page_no, content FROM xwiki_pages WHERE document_id = ? ORDER BY page_no",
          (doc_id,),
      ).fetchall()
      known_domains = [row[0] for row in conn.execute("SELECT DISTINCT domain FROM xwiki_entities").fetchall()]
    if not meta or not pages:
      return {"compiled": 0, "created": 0, "updated": 0}
    title = meta["title"]
    full_text = "\n\n".join([f"--- Page {row['page_no']} ---\n{row['content']}" for row in pages])
    entities = await self._extract_entities(title, full_text, known_domains)
    counts = {"compiled": 0, "created": 0, "updated": 0}
    for item in entities:
      name = (item.get("name") or "").strip()
      domain = (item.get("domain") or "未分类").strip()
      if not name:
        continue
      with self._db.connection() as conn:
        row = conn.execute(
            "SELECT consensus_summary, attributes_json, source_links_json, created_at "
            "FROM xwiki_entities WHERE entity_name = ?",
            (name,),
        ).fetchone()
      previous = row["consensus_summary"] if row else None
      previous_links = json.loads(row["source_links_json"]) if row else []
      created_at = row["created_at"] if row else datetime.now().isoformat()
      merged, attrs = await self._consensus(
          name=name,
          domain=domain,
          context=full_text,
          previous=previous,
      )
      if doc_id not in previous_links:
        previous_links.insert(0, doc_id)
      with self._db.connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO xwiki_entities "
            "(entity_name, domain, consensus_summary, attributes_json, source_links_json, updated_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                domain,
                merged,
                json.dumps(attrs, ensure_ascii=False),
                json.dumps(previous_links, ensure_ascii=False),
                datetime.now().isoformat(),
                created_at,
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO xwiki_entity_links (entity_name, document_id) VALUES (?, ?)",
            (name, doc_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO xwiki_compile_state (document_id, title, status, error, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                doc_id,
                title,
                "compiled",
                None,
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
      with self._db.connection() as conn:
        row = dict(conn.execute(
            "SELECT * FROM xwiki_entities WHERE entity_name = ?",
            (name,),
        ).fetchone())
      write_entity_file(self._workspace, row)
      counts["compiled"] += 1
      if previous is None:
        counts["created"] += 1
      else:
        counts["updated"] += 1
    return counts

  async def run(self) -> dict[str, int]:
    with self._db.connection() as conn:
      todo = [
          row["document_id"]
          for row in conn.execute(
              "SELECT document_id, title FROM xwiki_documents"
          ).fetchall()
      ]
    compiled = created = updated = 0
    for i in range(0, len(todo), self._batch_size):
      batch = todo[i : i + self._batch_size]
      for doc_id in batch:
        stats = await self._compile_document(doc_id)
        compiled += stats["compiled"]
        created += stats["created"]
        updated += stats["updated"]
    return {
        "documents_seen": len(todo),
        "compiled": compiled,
        "created": created,
        "updated": updated,
    }
