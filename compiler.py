"""
Wiki 深度编译器 (Deep Full-Text Compiler) - 无截断全量版

职责：
1. 移除机械截断：确保合并知识点时看到的是 Batch 内的完整原文。
2. 动态 Batch：平衡阅读深度与模型窗口。
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, List, Dict

from pydantic import BaseModel, Field

from openai_client import basic_chat

# --- 数据模型 ---

class EntityListLLM(BaseModel):
    entities: List[Dict[str, str]] = Field(description="List of {name, domain}")

class ConsensusLLM(BaseModel):
    new_consensus: str = Field(description="深度整合后的最新定义")
    key_attributes: Dict[str, str] = Field(default_factory=dict)

# --- 核心逻辑 ---

class DeepKnowledgeCompiler:
    def __init__(self, db_path: str, table_prefix: str = "kb", concurrency: int = 5, batch_size: int = 5) -> None:
        self.db_path = Path(db_path).resolve()
        self.prefix = table_prefix
        self.meta_table = f"{table_prefix}_knowledge"
        self.wiki_table = f"{table_prefix}_entities" 
        self.link_table = f"{table_prefix}_entity_links" 
        self.page_table = f"{table_prefix}_pages"
        self.log_table = f"{table_prefix}_logs"
        self.concurrency = concurrency
        self.batch_size = batch_size
        self._chat_client = basic_chat()
        self.processed_docs = 0

    def _connect_db(self):
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")

    async def _compile_batch(self, article_id: str, title: str, pages: List[Dict[str, Any]], domains: List[str]):
        """编译一组页面中的知识点"""
        # 拼接 Batch 内所有页面的完整原文，不截断
        batch_text = "\n\n".join([f"--- Page {p['page_no']} ---\n{p['content']}" for p in pages])
        
        try:
            # 1. 识别实体
            resp = self._chat_client.basic_chat_with_structured_output(
                messages=[
                    {"role": "system", "content": f"你是一个政务政策分析专家。请从给定的政策原文片段中识别所有核心实体。参考领域：{domains}"},
                    {"role": "user", "content": f"文档标题: {title}\n原文内容:\n{batch_text}"}
                ],
                response_format=EntityListLLM
            )
            
            for item in resp.choices[0].message.parsed.entities:
                name, domain = item.get("name"), item.get("domain")
                if not name: continue
                
                # 2. 知识整合
                old = self._conn.execute(f"SELECT consensus_summary, source_links_json, attributes_json FROM {self.wiki_table} WHERE entity_name=?", (name,)).fetchone()
                old_con = old[0] if old else "尚无定义。"
                links, attrs = (json.loads(old[1]) if old else []), (json.loads(old[2]) if old else {})
                
                # 再次强调：合并时传入完整的 batch_text，绝不截断
                comp_resp = self._chat_client.basic_chat_with_structured_output(
                    messages=[
                        {"role": "system", "content": "你是一个政务政策知识整合专家。"},
                        {"role": "user", "content": f"实体: {name}\n旧共识: {old_con}\n新发现原文: {batch_text}"}
                    ],
                    response_format=ConsensusLLM
                )
                res = comp_resp.choices[0].message.parsed
                
                if article_id not in links: links.insert(0, article_id)
                
                # 3. 更新 Wiki
                self._conn.execute(f"INSERT OR REPLACE INTO {self.wiki_table} VALUES (?,?,?,?,?,?)", 
                                  (name, domain, res.new_consensus, json.dumps({**attrs, **res.key_attributes}, ensure_ascii=False), 
                                   json.dumps(links, ensure_ascii=False), datetime.now().isoformat()))
                self._conn.execute(f"INSERT OR IGNORE INTO {self.link_table} VALUES (?, ?)", (name, article_id))
            
            self._conn.commit()
        except Exception as e:
            print(f"      !!! Batch Failed: {e}")

    async def _process_document(self, article_id: str, title: str, sem: asyncio.Semaphore, idx: int, total: int):
        async with sem:
            print(f"[{idx}/{total}] Deep Compiling: {title}")
            cur = self._conn.execute(f"SELECT page_no, content FROM {self.page_table} WHERE article_id=? ORDER BY page_no", (article_id,))
            all_pages = [{"page_no": r[0], "content": r[1]} for r in cur.fetchall()]
            
            domain_cur = self._conn.execute(f"SELECT DISTINCT domain FROM {self.wiki_table} LIMIT 50")
            domains = [r[0] for r in domain_cur.fetchall()]
            
            for i in range(0, len(all_pages), self.batch_size):
                batch = all_pages[i:i + self.batch_size]
                print(f"    - Processing Pages {batch[0]['page_no']} - {batch[-1]['page_no']}...")
                await self._compile_batch(article_id, title, batch, domains)
            
            self.processed_docs += 1
            print(f"[{idx}/{total}] Completed: {title}")

    async def run(self, force_all: bool = False):
        self._connect_db()
        if force_all:
            cursor = self._conn.execute(f"SELECT article_id, title FROM {self.meta_table}")
        else:
            cursor = self._conn.execute(f"SELECT m.article_id, m.title FROM {self.meta_table} m LEFT JOIN {self.link_table} l ON m.article_id = l.article_id WHERE l.article_id IS NULL")
        
        tasks = cursor.fetchall()
        total = len(tasks)
        print(f"\n[Deep Compiler] 待处理文档: {total}\n")
        
        sem = asyncio.Semaphore(self.concurrency)
        await asyncio.gather(*[self._process_document(r[0], r[1], sem, i+1, total) for i, r in enumerate(tasks)])
        self._conn.close()

if __name__ == "__main__":
    DB_PATH = "data/wiki_v2.sqlite" 
    # batch_size 设为 3，稍微减小一点并发阅读页数，以确保不截断的情况下也不超出模型 Token 限制
    compiler = DeepKnowledgeCompiler(db_path=DB_PATH, table_prefix="policy", concurrency=5, batch_size=3)
    asyncio.run(compiler.run(force_all=False))
