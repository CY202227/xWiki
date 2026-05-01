"""
Wiki 健康检查器 (Health Checker)

职责：
1. 孤儿探测：发现那些被提到但没有独立 Wiki 页面的实体。
2. 矛盾检查：请 LLM 扫描 Wiki 表，寻找内容冲突的条目。
3. 陈旧度审计：列出长时间未更新的核心知识点。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List, Dict, Any
from openai_client import basic_chat

class WikiHealthChecker:
    def __init__(self, db_path: str, table_prefix: str = "kb"):
        self.db_path = Path(db_path).resolve()
        self.prefix = table_prefix
        self.wiki_table = f"{table_prefix}_entities"
        self.log_table = f"{table_prefix}_logs"
        self.client = basic_chat()

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def scan_orphans(self):
        """寻找被引用但未定义的实体"""
        print("[*] 正在扫描孤儿实体...")
        # 逻辑：从元数据的 referenced_entities 中寻找不在 wiki_table 中的项
        pass # 后续可实现

    def check_contradictions(self):
        """扫描 Wiki 条目，寻找潜在冲突"""
        print("[*] 正在执行语义矛盾检查...")
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            entities = conn.execute(f"SELECT entity_name, consensus_summary FROM {self.wiki_table} LIMIT 20").fetchall()
            
            # 这里将多个实体的摘要丢给 LLM 进行全局一致性检查
            context = "\n".join([f"[{e['entity_name']}]: {e['consensus_summary']}" for e in entities])
            
            resp = self.client.client.chat.completions.create(
                model=self.client.model_name,
                messages=[
                    {"role": "system", "content": "你是一个审计专家。请检查以下 Wiki 条目之间是否存在逻辑自相矛盾或过时的说法。若有，请指出。"},
                    {"role": "user", "content": context}
                ]
            )
            print("\n--- 审计报告 ---")
            print(resp.choices[0].message.content)

if __name__ == "__main__":
    checker = WikiHealthChecker("data/wiki_v4/wiki_v4.sqlite", "policy")
    checker.check_contradictions()
