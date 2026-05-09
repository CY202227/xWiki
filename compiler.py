"""
Wiki 深度编译器 (Deep Full-Text Compiler) - 无截断全量版

职责：
1. 移除机械截断：确保合并知识点时看到的是 Batch 内的完整原文。
2. 动态 Batch：平衡阅读深度与模型窗口。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from openai_client import basic_chat

# --- 数据模型 ---

class EntityListLLM(BaseModel):
    entities: list[dict[str, str]] = Field(
        description="List of {name, domain}"
    )

class ConsensusLLM(BaseModel):
    new_consensus: str = Field(description="深度整合后的最新定义")
    key_attributes: dict[str, str] = Field(default_factory=dict)

# --- 核心逻辑 ---

class DeepKnowledgeCompiler:
    def __init__(
        self,
        db_path: str,
        table_prefix: str = "kb",
        concurrency: int = 5,
        batch_size: int = 5,
    ) -> None:
        self.db_path = Path(db_path).resolve()
        self.prefix = table_prefix
        self.meta_table = f"{table_prefix}_knowledge"
        self.wiki_table = f"{table_prefix}_entities"
        self.link_table = f"{table_prefix}_entity_links"
        self.page_table = f"{table_prefix}_pages"
        self.log_table = f"{table_prefix}_logs"
        self.state_table = f"{table_prefix}_compile_state"
        self.concurrency = concurrency
        self.batch_size = batch_size
        self._chat_client = basic_chat()
        self.processed_docs = 0
        self._db_lock = asyncio.Lock()

    def _connect_db(self):
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_runtime_schema()

    def _ensure_runtime_schema(self) -> None:
        self._conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self.wiki_table} ("
            "entity_name TEXT PRIMARY KEY, domain TEXT, "
            "consensus_summary TEXT, attributes_json TEXT, "
            "source_links_json TEXT, updated_at TEXT)"
        )
        self._conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self.link_table} ("
            "entity_name TEXT, article_id TEXT, "
            "PRIMARY KEY (entity_name, article_id))"
        )
        self._conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self.state_table} ("
            "article_id TEXT PRIMARY KEY, title TEXT, status TEXT, "
            "error TEXT, updated_at TEXT)"
        )
        self._conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self.log_table} ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, "
            "description TEXT, timestamp TEXT)"
        )
        now = datetime.now().isoformat()
        self._conn.execute(
            f"INSERT OR IGNORE INTO {self.state_table} "
            "(article_id, title, status, error, updated_at) "
            "SELECT m.article_id, m.title, 'success', NULL, ? "
            f"FROM {self.meta_table} m "
            f"WHERE EXISTS (SELECT 1 FROM {self.link_table} l "
            "WHERE l.article_id = m.article_id)",
            (now,),
        )
        self._conn.commit()

    def _log_event(self, event_type: str, description: str) -> None:
        self._conn.execute(
            f"INSERT INTO {self.log_table} "
            "(event_type, description, timestamp) VALUES (?, ?, ?)",
            (event_type, description, datetime.now().isoformat()),
        )

    def _mark_document_status(
        self,
        article_id: str,
        title: str,
        status: str,
        error: str | None = None,
    ) -> None:
        self._conn.execute(
            f"INSERT OR REPLACE INTO {self.state_table} "
            "(article_id, title, status, error, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (article_id, title, status, error, datetime.now().isoformat()),
        )

    def _get_domains(self) -> list[str]:
        cursor = self._conn.execute(
            f"SELECT DISTINCT domain FROM {self.wiki_table} "
            "WHERE domain IS NOT NULL AND domain != '' LIMIT 50"
        )
        return [row[0] for row in cursor.fetchall()]

    def _is_document_title(self, entity_name: str, title: str) -> bool:
        clean_entity = entity_name.strip("《》“”\"' ")
        clean_title = title.strip("《》“”\"' ")
        return clean_entity == clean_title

    async def _upsert_entity(
        self,
        article_id: str,
        name: str,
        domain: str,
        consensus: str,
        attributes: dict[str, str],
    ) -> None:
        async with self._db_lock:
            old = self._conn.execute(
                f"SELECT source_links_json, attributes_json "
                f"FROM {self.wiki_table} WHERE entity_name = ?",
                (name,),
            ).fetchone()
            links = json.loads(old[0]) if old and old[0] else []
            old_attributes = json.loads(old[1]) if old and old[1] else {}
            if article_id not in links:
                links.insert(0, article_id)

            self._conn.execute(
                f"INSERT OR REPLACE INTO {self.wiki_table} VALUES "
                "(?, ?, ?, ?, ?, ?)",
                (
                    name,
                    domain,
                    consensus,
                    json.dumps(
                        {**old_attributes, **attributes},
                        ensure_ascii=False,
                    ),
                    json.dumps(links, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            self._conn.execute(
                f"INSERT OR IGNORE INTO {self.link_table} VALUES (?, ?)",
                (name, article_id),
            )

    async def _compile_batch(
        self,
        article_id: str,
        title: str,
        pages: list[dict[str, Any]],
        domains: list[str],
    ) -> None:
        """编译一组页面中的知识点"""
        # 拼接 Batch 内所有页面的完整原文，不截断
        batch_text = "\n\n".join(
            f"--- Page {p['page_no']} ---\n{p['content']}" for p in pages
        )

        resp = self._chat_client.basic_chat_with_structured_output(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一个政务政策分析专家。请只抽取可复用的政策"
                        "实体、制度、事项、条件、部门、对象或工具。"
                        "不要把文档标题、文件名、版本号、章节标题当实体。"
                        "domain 必须是 2-6 字中文领域名；优先复用参考领域："
                        f"{domains}"
                    ),
                },
                {
                    "role": "user",
                    "content": f"文档标题: {title}\n原文内容:\n{batch_text}",
                },
            ],
            response_format=EntityListLLM,
        )

        for item in resp.choices[0].message.parsed.entities:
            name = (item.get("name") or "").strip()
            domain = (item.get("domain") or "政策").strip()
            if not name or self._is_document_title(name, title):
                continue

            old = self._conn.execute(
                f"SELECT consensus_summary FROM {self.wiki_table} "
                "WHERE entity_name = ?",
                (name,),
            ).fetchone()
            old_con = old[0] if old else "尚无定义。"
            comp_resp = self._chat_client.basic_chat_with_structured_output(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个政务政策知识整合专家。输出应是百科式"
                            "定义和适用规则，不要使用“已更新”“本次新增”"
                            "等过程描述。核心结论需能回溯到原文。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"实体: {name}\n旧共识: {old_con}\n"
                            f"新发现原文: {batch_text}"
                        ),
                    },
                ],
                response_format=ConsensusLLM,
            )
            res = comp_resp.choices[0].message.parsed
            await self._upsert_entity(
                article_id=article_id,
                name=name,
                domain=domain,
                consensus=res.new_consensus,
                attributes=res.key_attributes,
            )

    async def _process_document(
        self,
        article_id: str,
        title: str,
        sem: asyncio.Semaphore,
        idx: int,
        total: int,
    ) -> None:
        async with sem:
            print(f"[{idx}/{total}] Deep Compiling: {title}")
            self._mark_document_status(article_id, title, "running")
            self._conn.commit()
            try:
                cur = self._conn.execute(
                    f"SELECT page_no, content FROM {self.page_table} "
                    "WHERE article_id = ? ORDER BY page_no",
                    (article_id,),
                )
                all_pages = [
                    {"page_no": row[0], "content": row[1]}
                    for row in cur.fetchall()
                ]
                domains = self._get_domains()

                for i in range(0, len(all_pages), self.batch_size):
                    batch = all_pages[i:i + self.batch_size]
                    print(
                        f"    - Processing Pages {batch[0]['page_no']} - "
                        f"{batch[-1]['page_no']}..."
                    )
                    await self._compile_batch(article_id, title, batch, domains)

                self.processed_docs += 1
                self._mark_document_status(article_id, title, "success")
                self._log_event("compile_success", f"完成编译：{title}")
                self._conn.commit()
                print(f"[{idx}/{total}] Completed: {title}")
            except Exception as error:
                self._mark_document_status(
                    article_id,
                    title,
                    "failed",
                    repr(error),
                )
                self._log_event("compile_failed", f"{title}: {error!r}")
                self._conn.commit()
                print(f"      !!! Document Failed: {error}")

    async def run(self, force_all: bool = False):
        self._connect_db()
        if force_all:
            cursor = self._conn.execute(
                f"SELECT article_id, title FROM {self.meta_table}"
            )
        else:
            cursor = self._conn.execute(
                f"SELECT m.article_id, m.title FROM {self.meta_table} m "
                f"LEFT JOIN {self.state_table} s "
                "ON m.article_id = s.article_id "
                "WHERE s.status IS NULL OR s.status != 'success'"
            )

        tasks = cursor.fetchall()
        total = len(tasks)
        print(f"\n[Deep Compiler] 待处理文档: {total}\n")

        sem = asyncio.Semaphore(self.concurrency)
        await asyncio.gather(
            *[
                self._process_document(row[0], row[1], sem, i + 1, total)
                for i, row in enumerate(tasks)
            ]
        )
        self._conn.close()

    def add_custom_synthesis(
        self,
        entity_name: str,
        domain: str,
        content: str,
        source_ids: list[str],
    ) -> None:
        conn = sqlite3.connect(str(self.db_path))
        self._conn = conn
        self._ensure_runtime_schema()
        try:
            old = self._conn.execute(
                f"SELECT source_links_json, attributes_json "
                f"FROM {self.wiki_table} WHERE entity_name = ?",
                (entity_name,),
            ).fetchone()
            links = json.loads(old[0]) if old and old[0] else []
            attributes = json.loads(old[1]) if old and old[1] else {}
            for article_id in reversed(source_ids):
                if article_id not in links:
                    links.insert(0, article_id)

            self._conn.execute(
                f"INSERT OR REPLACE INTO {self.wiki_table} VALUES "
                "(?, ?, ?, ?, ?, ?)",
                (
                    entity_name,
                    domain,
                    content,
                    json.dumps(attributes, ensure_ascii=False),
                    json.dumps(links, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            for article_id in source_ids:
                self._conn.execute(
                    f"INSERT OR IGNORE INTO {self.link_table} VALUES (?, ?)",
                    (entity_name, article_id),
                )
            self._log_event("wiki_backflow", f"回流知识点：{entity_name}")
            self._conn.commit()
        finally:
            self._conn.close()


KnowledgeCompiler = DeepKnowledgeCompiler

if __name__ == "__main__":
    DB_PATH = "data/wiki_v4/wiki_v4.sqlite"
    # batch_size 设为 3，稍微减小一点并发阅读页数，以确保不截断的情况下也不超出模型 Token 限制
    compiler = DeepKnowledgeCompiler(db_path=DB_PATH, table_prefix="policy", concurrency=5, batch_size=3)
    asyncio.run(compiler.run(force_all=False))
