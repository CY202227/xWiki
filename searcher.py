"""
Wiki 搜索器 (Searcher) - MCP 兼容版

职责：
1. 语义 Wiki 搜索：优先返回由 Agent 编译后的核心实体共识。
2. 全文索引检索：在原始文档库中执行 FTS5 搜索。
3. 知识图谱导航：获取库的顶级分类和统计画像。
4. 正文精准提取：读取特定文档的指定页码正文。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, List, Dict, Optional

class KnowledgeSearcher:
    def __init__(self, db_path: str, table_prefix: str = "kb") -> None:
        self.db_path = Path(db_path).resolve()
        self.prefix = table_prefix
        # 表名映射
        self.meta_table = f"{table_prefix}_knowledge"
        self.page_table = f"{table_prefix}_pages"
        self.fts_table = f"{table_prefix}_fts"
        self.wiki_table = f"{table_prefix}_entities"
        self.link_table = f"{table_prefix}_entity_links"

    def _get_conn(self):
        # MCP 环境建议每次调用建立连接，或使用连接池
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def get_overview(self) -> Dict[str, Any]:
        """获取知识库全景：分类统计与实体画像"""
        with self._get_conn() as conn:
            # 统计成熟分类
            types_cur = conn.execute(f"SELECT doc_type, COUNT(*) as cnt FROM {self.meta_table} GROUP BY doc_type ORDER BY cnt DESC LIMIT 20")
            doc_types = {row['doc_type']: row['cnt'] for row in types_cur.fetchall()}
            
            # 统计顶级领域
            domain_cur = conn.execute(f"SELECT domain, COUNT(*) as cnt FROM {self.wiki_table} GROUP BY domain ORDER BY cnt DESC LIMIT 20")
            domains = {row['domain']: row['cnt'] for row in domain_cur.fetchall()}
            
            total_docs = conn.execute(f"SELECT COUNT(*) FROM {self.meta_table}").fetchone()[0]
            total_entities = conn.execute(f"SELECT COUNT(*) FROM {self.wiki_table}").fetchone()[0]
            
            return {
                "total_documents": total_docs,
                "total_wiki_entities": total_entities,
                "top_categories": doc_types,
                "top_domains": domains
            }

    def list_wiki_index(self, domain: Optional[str] = None, limit: int = 100) -> List[str]:
        """【透明度工具】：列出 Wiki 中的所有实体名称（按领域过滤）"""
        with self._get_conn() as conn:
            sql = f"SELECT entity_name FROM {self.wiki_table}"
            params = []
            if domain:
                sql += " WHERE domain = ?"
                params.append(domain)
            sql += " ORDER BY entity_name LIMIT ?"
            params.append(limit)
            cur = conn.execute(sql, params)
            return [row['entity_name'] for row in cur.fetchall()]

    def get_recent_activity(self, limit: int = 10) -> List[Dict[str, Any]]:
        """【历史感工具】：查看最近创建或更新的 Wiki 词条和审计日志"""
        with self._get_conn() as conn:
            sql = f"SELECT event_type, description, timestamp FROM {self.prefix}_logs ORDER BY timestamp DESC LIMIT ?"
            cur = conn.execute(sql, (limit,))
            return [dict(row) for row in cur.fetchall()]

    def search_wiki(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """搜索 Wiki 实体共识（优先）"""
        with self._get_conn() as conn:
            # 这里使用模糊匹配实体名和定义
            sql = f"SELECT * FROM {self.wiki_table} WHERE entity_name LIKE ? OR consensus_summary LIKE ? LIMIT ?"
            cur = conn.execute(sql, (f"%{query}%", f"%{query}%", limit))
            return [dict(row) for row in cur.fetchall()]

    def search_documents(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """【治理管道】：多层回退检索 (Strict AND -> Broad OR -> LIKE)"""
        import re
        from datetime import datetime
        
        # 1. 清理分词
        tokens = [t for t in re.split(r"\s+", query.strip()) if t]
        if not tokens: return []
        
        curr_year = datetime.now().year
        
        def _execute(fts_q: str):
            # 引入 v5 的评分机制：FTS Rank + 时效性权重
            sql = f"""
                SELECT m.article_id, m.title, m.doc_date as publication_time, m.doc_type, 
                       snippet({self.fts_table}, 3, '【', '】', '...', 40) as context_snippet,
                       f.rank * (1.0 + 0.05 * ({curr_year} - CAST(SUBSTR(COALESCE(m.doc_date, '2000-01-01'), 1, 4) AS INTEGER))) AS score
                FROM {self.fts_table} f
                JOIN {self.meta_table} m ON f.article_id = m.article_id
                WHERE {self.fts_table} MATCH ?
                ORDER BY score ASC
                LIMIT ?
            """
            cur = conn.execute(sql, (fts_q, limit))
            return [dict(row) for row in cur.fetchall()]

        with self._get_conn() as conn:
            try:
                # Layer 0: Strict AND
                fts_and = " AND ".join([f'"{t.replace('"', '""')}"' for t in tokens])
                res = _execute(fts_and)
                if res: return res
                
                # Layer 1: Broad OR
                fts_or = " OR ".join([f'"{t.replace('"', '""')}"' for t in tokens])
                res = _execute(fts_or)
                if res: return res
            except Exception as e:
                print(f"   [Searcher Debug] FTS Failed: {e}")

            # Layer 2: Final Fallback (LIKE)
            sql_like = f"SELECT article_id, title, doc_date, summary as context_snippet FROM {self.meta_table} WHERE title LIKE ? OR summary LIKE ? LIMIT ?"
            cur = conn.execute(sql_like, (f"%{tokens[0]}%", f"%{tokens[0]}%", limit))
            return [dict(row) for row in cur.fetchall()]

    def get_entity_evidence(self, entity_name: str, limit: int = 3) -> Dict[str, Any]:
        """【核心核实工具】：获取实体的编译定义，并强制附带关联文档的原始摘要/片段进行比对"""
        with self._get_conn() as conn:
            entity = conn.execute(f"SELECT * FROM {self.wiki_table} WHERE entity_name = ?", (entity_name,)).fetchone()
            if not entity:
                return {"error": "Entity not found."}
            
            # 获取关联的文档以及它们的原始摘要（用于核实编译内容）
            links = conn.execute(f"""
                SELECT m.article_id, m.title, m.doc_date, m.summary as original_summary
                FROM {self.link_table} l
                JOIN {self.meta_table} m ON l.article_id = m.article_id
                WHERE l.entity_name = ?
                ORDER BY m.doc_date DESC LIMIT ?
            """, (entity_name, limit)).fetchall()
            
            res = dict(entity)
            res['wiki_consensus'] = res.pop('consensus_summary') # 改名以明确这是编译后的
            res['verifiable_evidence'] = [dict(l) for l in links] # 原始证据
            return res

    def read_pages(self, article_id: str, page_nos: List[int]) -> str:
        """读取指定文档的特定页码内容"""
        with self._get_conn() as conn:
            placeholders = ",".join(["?"] * len(page_nos))
            sql = f"SELECT page_no, content FROM {self.page_table} WHERE article_id = ? AND page_no IN ({placeholders}) ORDER BY page_no"
            rows = conn.execute(sql, [article_id] + page_nos).fetchall()
            return "\n\n".join([f"--- Page {r['page_no']} ---\n{r['content']}" for r in rows])

# --- MCP 挂载示例用法 ---
if __name__ == "__main__":
    # 配置
    DB_PATH = "data/wiki_v4/wiki_v4.sqlite"
    PREFIX = "policy"
    
    searcher = KnowledgeSearcher(db_path=DB_PATH, table_prefix=PREFIX)
    
    # 示例 1: 查看库概览
    print("KB Overview:", json.dumps(searcher.get_overview(), ensure_ascii=False, indent=2))
    
    # 示例 2: 搜索 Wiki
    print("Wiki Search:", searcher.search_wiki("跨境融资"))
