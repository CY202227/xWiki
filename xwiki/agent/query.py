"""Query orchestration and evidence-driven answer path."""

from __future__ import annotations

import json
from typing import Any, Dict, List
from pydantic import BaseModel, Field

from ..llm import XWikiLLM, _NoCredentialsError
from ..searcher import XWikiSearcher
from .tools import QueryTools
from ..agent._markdown import truncate


class QueryEngine:
  def __init__(self, searcher: XWikiSearcher, llm: XWikiLLM):
    self._searcher = searcher
    self._tools = QueryTools(searcher._db)
    self._llm = llm

  async def _backfill_wiki(self, question: str, answer: str) -> str | None:
    if not self._llm.has_credentials:
      return None

    class Backflow(BaseModel):
      title: str = Field(default="")
      content: str = Field(default="")

    resp = self._llm.structured(
        messages=[
            {
                "role": "system",
                "content": "将问题与关键答复压缩为一个可回流的 wiki 短摘要。",
            },
            {"role": "user", "content": f"Q: {question}\nA: {answer}"},
        ],
        response_model=Backflow,
    )
    parsed = resp.choices[0].message.parsed
    return parsed.content if getattr(parsed, "content", "") else None

  async def ask(self, question: str, top_k: int = 4, backflow: bool = False) -> Dict[str, Any]:
    wiki_hits = self._searcher.search_wiki(question, limit=top_k)
    doc_hits = []
    if len(wiki_hits) < 2:
      doc_hits = self._searcher.search_documents(question, limit=top_k)

    evidence_blocks = []
    for item in wiki_hits[:top_k]:
      evidence_blocks.append(
          {
              "type": "wiki",
              "name": item["entity_name"],
              "consensus": item["consensus_summary"][:250],
          },
      )
      info = self._tools.get_entity_evidence(item["entity_name"], limit=2)
      evidence_blocks.append({"type": "evidence", "payload": info})

    for item in doc_hits[: top_k - len(wiki_hits)]:
      evidence_blocks.append(
          {
              "type": "document",
              "title": item["title"],
              "snippet": item.get("context_snippet", ""),
          },
      )

    if not self._llm.has_credentials:
      return {
          "question": question,
          "answer": (
              "当前未配置 LLM key，仅返回可检索证据。"
              "请配置 OPENAI_API_KEY 后获得生成式回答。"
          ),
          "evidence": evidence_blocks,
      }

    response = self._llm.complete(
        messages=[
            {
                "role": "system",
                "content": (
                    "给出结论性回答并优先使用 wiki 证据；"
                    "每条结论必须附带来源标识 entity_name 或 document_id。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"问题: {question}\n\n可用证据:\n{json.dumps(evidence_blocks, ensure_ascii=False)}"
                ),
            },
        ]
    )
    result = {
        "question": question,
        "answer": response,
        "evidence": evidence_blocks,
        "source_count": len(evidence_blocks),
    }
    if backflow:
      try:
        item = await self._backfill_wiki(question, response)
        if item:
          result["backflow_hint"] = truncate(item, 140)
      except _NoCredentialsError:
        pass
    return result
