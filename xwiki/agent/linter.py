"""LLM-based knowledge lint checks."""

from __future__ import annotations

from typing import Any, Dict

from ..llm import XWikiLLM


class KnowledgeLinter:
  def __init__(self, llm: XWikiLLM, db):
    self._llm = llm
    self._db = db

  def _collect_candidates(self) -> str:
    with self._db.connection() as conn:
      rows = conn.execute(
          "SELECT entity_name, consensus_summary FROM xwiki_entities LIMIT 40"
      ).fetchall()
    return "\n".join([f"[{row['entity_name']}] {row['consensus_summary']}" for row in rows])

  async def check_contradictions(self) -> Dict[str, Any]:
    candidates = self._collect_candidates()
    if not candidates:
      return {"status": "skipped", "reason": "no candidates"}
    if not self._llm.has_credentials:
      return {"status": "skipped", "reason": "llm unavailable"}
    response = self._llm.complete(
        messages=[
            {
                "role": "system",
                "content": "做一次冲突扫描，发现可能自相矛盾的定义并指出证据。",
            },
            {"role": "user", "content": candidates},
        ]
    )
    return {
        "status": "ok",
        "checked": len(candidates.splitlines()),
        "report": response,
    }

  async def check_quality(self, sample_limit: int = 20) -> Dict[str, Any]:
    with self._db.connection() as conn:
      rows = conn.execute(
          "SELECT entity_name, consensus_summary FROM xwiki_entities LIMIT ?",
          (sample_limit,),
      ).fetchall()
    if not rows:
      return {"status": "skipped", "reason": "no entities"}
    if not self._llm.has_credentials:
      return {"status": "skipped", "reason": "llm unavailable"}
    text = "\n".join([f"{r['entity_name']}: {r['consensus_summary']}" for r in rows])
    response = self._llm.complete(
        messages=[
            {
                "role": "system",
                "content": "检查定义质量（可追溯性、歧义、冗余）并给出可执行建议。",
            },
            {"role": "user", "content": text},
        ],
    )
    return {
        "status": "ok",
        "checked": len(rows),
        "report": response,
    }
