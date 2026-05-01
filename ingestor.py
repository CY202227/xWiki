"""
Wiki 采集器 (Ingestor) - 零图片干扰版
特性：
1. 彻底清洗 Base64：在处理前剔除所有图片编码，确保 Token 使用效率。
2. 数据库瘦身：不再将图片原始编码存入 SQL。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, List, Dict

from pydantic import BaseModel, Field

from openai_client import basic_chat

PROCESSOR_VERSION = "2026.04.08.v5-no-images"

# --- 数据模型 ---

class PageSummaryLLM(BaseModel):
    page_summary: str
    last_active_key: str = Field(default="")

class OutlineLLM(BaseModel):
    items: List[Dict[str, Any]] = Field(description="List of {title, start_page, end_page, brief}")

class MetaEntryLLM(BaseModel):
    doc_date: str = Field(description="YYYY-MM-DD")
    canonical_title: str = Field(description="标准化名称")
    summary: str = Field(description="深度内容综述")
    topic_tags: List[str] = Field(default_factory=list)
    doc_type: str = Field(description="分类名称")

@dataclass
class ParsedPage:
    page_no: int
    content: str
    summary: Optional[PageSummaryLLM] = None

# --- 核心逻辑 ---

class KnowledgeIngestor:
    def __init__(self, data_dir: str, db_path: str, table_prefix: str = "kb", concurrency: int = 10) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.db_path = Path(db_path).resolve()
        self.prefix = table_prefix
        self.meta_table = f"{table_prefix}_knowledge"
        self.page_table = f"{table_prefix}_pages"
        self.fts_table = f"{table_prefix}_fts"
        self.cache_table = f"{table_prefix}_processing_cache"
        self.concurrency = concurrency
        self._chat_client = basic_chat()
        self.success_count = 0
        self.skip_count = 0
        self.existing_types = [] 
        self.run_types = set() 
        self._db_lock = asyncio.Lock()

    def _connect_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"[*] Connecting to database: {self.db_path}")
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()
        self._refresh_types()

    def _refresh_types(self):
        try:
            cursor = self._conn.execute(f"SELECT doc_type FROM {self.meta_table} GROUP BY doc_type HAVING COUNT(*) >= 2 ORDER BY COUNT(*) DESC LIMIT 60")
            self.existing_types = [row[0] for row in cursor.fetchall()]
        except: pass

    def _ensure_schema(self):
        self._conn.execute(f"CREATE TABLE IF NOT EXISTS {self.meta_table} (article_id TEXT PRIMARY KEY, title TEXT, content_hash TEXT)")
        cols = {
            "canonical_title": "TEXT", "doc_date": "TEXT", "doc_type": "TEXT", 
            "summary": "TEXT", "topic_tags_json": "TEXT", "outline_json": "TEXT", 
            "page_summaries_json": "TEXT", "href": "TEXT", "total_pages": "INTEGER",
            "processor_version": "TEXT", "created_at": "TEXT", "updated_at": "TEXT"
        }
        for n, t in cols.items():
            try: self._conn.execute(f"ALTER TABLE {self.meta_table} ADD COLUMN {n} {t}")
            except: pass
        self._conn.execute(f"CREATE TABLE IF NOT EXISTS {self.page_table} (id INTEGER PRIMARY KEY AUTOINCREMENT, article_id TEXT, page_no INTEGER, content TEXT)")
        self._conn.execute(f"CREATE TABLE IF NOT EXISTS {self.cache_table} (content_hash TEXT, page_no INTEGER, processor_version TEXT, summary_json TEXT, PRIMARY KEY (content_hash, page_no, processor_version))")
        try: self._conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS {self.fts_table} USING fts5(article_id UNINDEXED, title, summary, raw_content)")
        except: pass
        self._conn.commit()

    def _clean_content(self, text: str) -> str:
        """【核心清洗】：移除所有的 Base64 图片字符串"""
        # 匹配 Markdown 中的 ![...] (data:image/...;base64,...)
        text = re.sub(r'!\[.*?\]\(data:image\/.*?;base64,.*?\)', '[IMAGE_REMOVED]', text)
        # 匹配 HTML 中的 src="data:image/...;base64,..."
        text = re.sub(r'src="data:image\/.*?;base64,.*?"', 'src="[IMAGE_REMOVED]"', text)
        # 匹配可能存在的独立 data:image 块
        text = re.sub(r'data:image\/.*?;base64,[A-Za-z0-9+/=]+', '[BASE64_DATA_REMOVED]', text)
        return text

    async def _call_llm_with_infinite_retry(self, messages: list, response_format: Any, doc_title: str):
        retry_count = 0
        while True:
            try:
                resp = self._chat_client.basic_chat_with_structured_output(
                    messages=messages,
                    response_format=response_format
                )
                print(resp.choices[0].message.parsed)
                return resp.choices[0].message.parsed
            except Exception as e:
                retry_count += 1
                wait_time = min(2 ** retry_count, 30)
                print(f"      [Retry] {doc_title}: 请求失败 ({e})。将在 {wait_time}s 后重试...")
                await asyncio.sleep(wait_time)

    async def _analyze_page(self, page_no: int, content: str, inherited: str, content_hash: str, doc_title: str) -> PageSummaryLLM:
        cursor = self._conn.execute(f"SELECT summary_json FROM {self.cache_table} WHERE content_hash=? AND page_no=? AND processor_version=?", (content_hash, page_no, PROCESSOR_VERSION))
        hit = cursor.fetchone()
        if hit: return PageSummaryLLM.model_validate_json(hit[0])
        
        res = await self._call_llm_with_infinite_retry(
            messages=[{"role": "system", "content": "提炼本页核心知识摘要。"}, {"role": "user", "content": f"Inherited Context: {inherited}\nPage Content:\n{content}"}],
            response_format=PageSummaryLLM,
            doc_title=f"{doc_title} (P{page_no})"
        )
        
        async with self._db_lock:
            self._conn.execute(f"INSERT OR REPLACE INTO {self.cache_table} VALUES (?,?,?,?)", (content_hash, page_no, PROCESSOR_VERSION, res.model_dump_json()))
            self._conn.commit()
        return res

    async def _process_file(self, file_path: Path, current_idx: int, total_files: int, sem: asyncio.Semaphore):
        title = file_path.stem
        href = f"/static/data/{file_path.name}"
        # 读取并立即清洗图片
        raw_content = file_path.read_text(encoding="utf-8", errors="replace")
        cleaned_content = self._clean_content(raw_content)
        
        content_hash = hashlib.md5(cleaned_content.encode()).hexdigest()
        article_id = hashlib.md5(href.encode()).hexdigest()

        if self._conn.execute(f"SELECT 1 FROM {self.meta_table} WHERE article_id=? AND content_hash=?", (article_id, content_hash)).fetchone():
            self.skip_count += 1; return

        async with sem:
            print(f"[{current_idx}/{total_files}] Processing: {title}")
            try:
                raw_parts = re.split(r"<!-- PAGE_(\d+) -->", cleaned_content)
                pages = [ParsedPage(page_no=int(raw_parts[i]), content=raw_parts[i+1].strip()) for i in range(1, len(raw_parts), 2)] if "<!-- PAGE_" in cleaned_content else [ParsedPage(page_no=1, content=cleaned_content.strip())]
                total_p = len(pages)
                
                summary_stream = ""
                last_key = ""
                for pg in pages:
                    pg.summary = await self._analyze_page(pg.page_no, pg.content, last_key, content_hash, title)
                    summary_stream += f" [Page {pg.page_no}]: {pg.summary.page_summary}"
                    last_key = pg.summary.last_active_key or last_key
            
                print(f"    - Generating Meta & Outline: {title}...")
                visible_types = sorted(list(set(self.existing_types) | self.run_types))[:60]
                
                meta_task = self._call_llm_with_infinite_retry(
                    messages=[
                        {"role": "system", "content": f"提取元数据。建议分类：{visible_types}"},
                        {"role": "user", "content": f"标题: {title}\n摘要流: {summary_stream}"}],
                    response_format=MetaEntryLLM, doc_title=title
                )
                
                outline_task = self._call_llm_with_infinite_retry(
                    messages=[
                        {"role": "system", "content": "生成结构化大纲。"},
                        {"role": "user", "content": f"标题: {title}\n摘要流: {summary_stream}"}],
                    response_format=OutlineLLM, doc_title=title
                )
                
                meta, outline = await asyncio.gather(meta_task, outline_task)
                self.run_types.add(meta.doc_type)

                async with self._db_lock:
                    data = {
                        "article_id": article_id, "title": title, "canonical_title": meta.canonical_title,
                        "doc_date": meta.doc_date, "doc_type": meta.doc_type, "content_hash": content_hash,
                        "processor_version": PROCESSOR_VERSION, "summary": meta.summary, 
                        "topic_tags_json": json.dumps(meta.topic_tags, ensure_ascii=False),
                        "outline_json": outline.model_dump_json(), 
                        "page_summaries_json": json.dumps([{"p":p.page_no, "s":p.summary.page_summary} for p in pages], ensure_ascii=False),
                        "href": href, "total_pages": total_p, "created_at": datetime.now().isoformat(), "updated_at": datetime.now().isoformat()
                    }
                    self._conn.execute(f"INSERT OR REPLACE INTO {self.meta_table} ({','.join(data.keys())}) VALUES ({','.join(['?']*len(data))})", tuple(data.values()))
                    self._conn.execute(f"DELETE FROM {self.page_table} WHERE article_id=?", (article_id,))
                    self._conn.executemany(f"INSERT INTO {self.page_table} (article_id, page_no, content) VALUES (?,?,?)", [(article_id, p.page_no, p.content) for p in pages])
                    self._conn.execute(f"DELETE FROM {self.fts_table} WHERE article_id=?", (article_id,))
                    self._conn.execute(f"INSERT INTO {self.fts_table} VALUES (?,?,?,?)", (article_id, title, meta.summary, cleaned_content))
                    self._conn.commit()
                
                self.success_count += 1
                print(f"[{current_idx}/{total_files}] Done: {title}")
            except Exception as e: print(f" !!! [Error] {title}: {e}")

    async def run(self):
        self._connect_db()
        files = sorted(list(self.data_dir.glob("*.md")))
        print(f"\n[Ingestor] Total: {len(files)} | Concurrency: {self.concurrency}\n")
        sem = asyncio.Semaphore(self.concurrency)
        await asyncio.gather(*[self._process_file(f, i+1, len(files), sem) for i, f in enumerate(files)])
        self._conn.close()

if __name__ == "__main__":
    DATA_DIR = "./input_md"
    DB_PATH = "data/wiki_v2.sqlite"
    ingestor = KnowledgeIngestor(DATA_DIR, DB_PATH, table_prefix="policy", concurrency=5)
    asyncio.run(ingestor.run())
