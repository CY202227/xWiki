"""Ingestion workflows: move files from inbox to raw and write normalized index."""

from __future__ import annotations

import json
from datetime import datetime

from .config import XWikiConfig
from .converter import MarkdownConverter, ParsedDocument
from .db import XWikiDatabase
from .llm import XWikiLLM
from .models import MetaEntryLLM, OutlineLLM, PageSummaryLLM
from .state import WorkspaceState


class SourceIndexer:
  """Read staged markdown sources, extract summaries and persist indexed rows."""

  def __init__(
      self,
      converter: MarkdownConverter,
      db: XWikiDatabase,
      llm: XWikiLLM,
      state: WorkspaceState,
      config: XWikiConfig,
  ) -> None:
    self._converter = converter
    self._db = db
    self._llm = llm
    self._state = state
    self._config = config

  async def _page_summary(self, page_no: int, content: str, inherited: str, doc_hash: str):
    if not self._llm.has_credentials:
      return PageSummaryLLM(page_summary=content[:120], last_active_key=inherited)
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT summary_json FROM xwiki_processing_cache "
          "WHERE content_hash=? AND page_no=? AND processor_version=?",
          (doc_hash, page_no, self._config.processor_version),
      ).fetchone()
    if row:
      return PageSummaryLLM.model_validate_json(row[0])

    resp = self._llm.structured(
        messages=[
            {
                "role": "system",
                "content": "提炼本页核心知识摘要，不要冗长，突出事实与术语。",
            },
            {"role": "user", "content": f"Inherited Context: {inherited}\nPage Content:\n{content}"},
        ],
        response_model=PageSummaryLLM,
    )
    parsed = resp.choices[0].message.parsed
    with self._db.connection() as conn:
      conn.execute(
          "INSERT OR REPLACE INTO xwiki_processing_cache "
          "(content_hash, page_no, processor_version, summary_json, created_at) "
          "VALUES (?, ?, ?, ?, ?)",
          (
              doc_hash,
              page_no,
              self._config.processor_version,
              parsed.model_dump_json(),
              datetime.now().isoformat(),
          ),
      )
      conn.commit()
    return parsed

  async def _meta_and_outline(self, title: str, summary_stream: str):
    if not self._llm.has_credentials:
      return (
          MetaEntryLLM(
              doc_date="",
              canonical_title=title,
              summary=summary_stream[:300],
              topic_tags=[],
              doc_type="未分类",
          ),
          OutlineLLM(items=[]),
      )
    meta = self._llm.structured(
        messages=[
            {
                "role": "system",
                "content": "提取文档元信息：分类、摘要、标准标题、标签。",
            },
            {"role": "user", "content": f"标题: {title}\n摘要流: {summary_stream}"},
        ],
        response_model=MetaEntryLLM,
    ).choices[0].message.parsed
    outline = self._llm.structured(
        messages=[
            {"role": "system", "content": "生成一个简短结构化目录，不要太长。"},
            {"role": "user", "content": f"标题: {title}\n摘要流: {summary_stream}"},
        ],
        response_model=OutlineLLM,
    ).choices[0].message.parsed
    return meta, outline

  async def index(self, document: ParsedDocument) -> None:
    page_summaries = []
    merged_summary = ""
    last_key = ""
    for page in document.pages:
      summary = await self._page_summary(
          page.page_no,
          page.content,
          inherited=last_key,
          doc_hash=document.content_hash,
      )
      merged_summary += f" [Page {page.page_no}] {summary.page_summary}"
      last_key = summary.last_active_key or last_key
      page_summaries.append({"page": page.page_no, "summary": summary.page_summary})

    meta, outline = await self._meta_and_outline(document.title, merged_summary)

    now = datetime.now().isoformat()
    with self._db.connection() as conn:
      conn.execute(
          "INSERT OR REPLACE INTO xwiki_documents ("
          "document_id, source_path, raw_path, title, canonical_title, doc_date, "
          "doc_type, summary, topic_tags_json, outline_json, page_summaries_json, "
          "content_hash, processor_version, status, created_at, updated_at"
          ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
          (
              document.document_id,
              str(document.source_path),
              str(document.raw_path),
              document.title,
              meta.canonical_title,
              meta.doc_date,
              meta.doc_type,
              meta.summary,
              json.dumps(meta.topic_tags, ensure_ascii=False),
              outline.model_dump_json(),
              json.dumps(page_summaries, ensure_ascii=False),
              document.content_hash,
              self._config.processor_version,
              "indexed",
              now,
              now,
          ),
      )
      conn.execute(
          "DELETE FROM xwiki_pages WHERE document_id=?",
          (document.document_id,),
      )
      for page in document.pages:
        conn.execute(
            "INSERT INTO xwiki_pages (document_id, page_no, content) VALUES (?, ?, ?)",
            (document.document_id, page.page_no, page.content),
        )
      conn.execute(
          "INSERT OR REPLACE INTO xwiki_fts "
          "(document_id, title, summary, raw_content) VALUES (?, ?, ?, ?)",
          (document.document_id, document.title, meta.summary, document.raw_text),
      )
      conn.execute(
          "INSERT OR REPLACE INTO xwiki_compile_state "
          "(document_id, title, status, error, updated_at) VALUES (?, ?, ?, ?, ?)",
          (document.document_id, document.title, "indexed", None, now),
      )
      conn.commit()
    self._state.set_document_status(document.document_id, "indexed")

  async def index_all(self, parsed_docs: list[ParsedDocument]) -> dict[str, int]:
    added = skipped = 0
    for item in parsed_docs:
      with self._db.connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM xwiki_documents WHERE document_id=? AND content_hash=?",
            (item.document_id, item.content_hash),
        ).fetchone()
      if row:
        skipped += 1
        continue
      await self.index(item)
      added += 1
    return {"added": added, "skipped": skipped}
