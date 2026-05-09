"""
Wiki 查看器 (Viewer) - 格式化展示知识百科内容
"""
import json
import sqlite3
import os
from pathlib import Path
from datetime import datetime

class WikiViewer:
    def __init__(self, db_path: str, table_prefix: str = "policy"):
        self.db_path = Path(db_path).resolve()
        self.wiki_table = f"{table_prefix}_entities"
        self.meta_table = f"{table_prefix}_knowledge"

    def _get_conn(self):
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)

    def _resolve_updated_column(self, conn: sqlite3.Connection) -> str:
        """返回实体表中可用的更新时间列名。"""
        rows = conn.execute(
            f"PRAGMA table_info({self.wiki_table})"
        ).fetchall()
        columns = {row[1] for row in rows}
        if "updated_at" in columns:
            return "updated_at"
        if "last_updated_at" in columns:
            return "last_updated_at"
        if "created_at" in columns:
            return "created_at"
        return ""

    def display_all_entities(self):
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        try:
            updated_column = self._resolve_updated_column(conn)
            if updated_column:
                entities = conn.execute(
                    f"SELECT * FROM {self.wiki_table} "
                    f"ORDER BY {updated_column} DESC"
                ).fetchall()
            else:
                entities = conn.execute(
                    f"SELECT * FROM {self.wiki_table}"
                ).fetchall()

            print(f"\n{'='*100}")
            print(f"{'Wiki 实体百科内容概览':^100}")
            print(f"{'='*100}\n")

            if not entities:
                print("   (库中尚无实体内容)")
                return

            for idx, entity in enumerate(entities):
                name = entity['entity_name']
                domain = entity['domain'] or "未分类"
                consensus = entity['consensus_summary']
                attrs = json.loads(entity['attributes_json'] or "{}")
                sources = json.loads(entity['source_links_json'] or "[]")
                updated = (
                    entity[updated_column]
                    if updated_column else "未知"
                )

                # 获取来源文件的标题
                source_titles = []
                if sources:
                    placeholders = ",".join(["?"] * len(sources))
                    rows = conn.execute(
                        f"SELECT title FROM {self.meta_table} "
                        f"WHERE article_id IN ({placeholders})",
                        sources,
                    ).fetchall()
                    source_titles = [row['title'] for row in rows]

                print(f"[{idx+1}] 实体名称: {name} ({domain})")
                print(f"    更新时间: {updated}")
                print(
                    f"    最新共识: {consensus[:200]}..."
                    if len(consensus) > 200
                    else f"    最新共识: {consensus}"
                )

                if attrs:
                    print(f"    关键属性:")
                    for k, v in attrs.items():
                        print(f"      - {k}: {v}")

                if source_titles:
                    print(f"    关联文件:")
                    for title in source_titles:
                        print(f"      * {title}")

                print(f"{'-'*100}")
        finally:
            conn.close()

if __name__ == "__main__":
    DB_PATH = "data/wiki_v4/wiki_v4.sqlite"
    viewer = WikiViewer(DB_PATH)
    viewer.display_all_entities()
