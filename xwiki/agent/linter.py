"""LLM-based knowledge lint checks."""

from __future__ import annotations

from typing import Any, Dict
import asyncio
import json

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
        from ..searcher import XWikiSearcher
        searcher = XWikiSearcher(self._db)
        records = []
        for row in rows:
            evidence = searcher.get_entity_evidence(row["entity_name"], limit=2)
            originals = [searcher.document_passages(source["document_id"], searcher._tokenize(row["entity_name"]), limit=1)
                         for source in evidence.get("evidence", [])]
            records.append({"entity_name": row["entity_name"], "consensus": row["consensus_summary"], "citations": evidence.get("citations", []), "originals": originals})
        return json.dumps(records, ensure_ascii=False)

    async def check_contradictions(self) -> Dict[str, Any]:
        candidates = self._collect_candidates()
        if not json.loads(candidates):
            return {"status": "skipped", "reason": "no candidates"}
        if not self._llm.has_credentials:
            return {"status": "skipped", "reason": "llm unavailable"}
        response = await asyncio.to_thread(self._llm.complete,
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
            "checked": len(json.loads(candidates)),
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
        text = "\n".join(
            [f"{r['entity_name']}: {r['consensus_summary']}" for r in rows]
        )
        response = await asyncio.to_thread(self._llm.complete,
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
