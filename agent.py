"""
Wiki 智能助手 (Agent) V3 - 深度迭代与共识进化版

核心机制：
1. 快速路径 (Wiki Path)：优先检索已有的百科共识。
2. 深度路径 (Deep Dive Path)：若共识不足，开启 v5 架构的多轮精读迭代模式。
3. 证据核实与回流：所有深读结论必须经过原文核实，并自动进化 Wiki。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import AsyncIterator, List, Dict, Any, Optional

from pydantic import BaseModel, Field

# 导入搜索器和编译器
from searcher import KnowledgeSearcher
from compiler import DeepKnowledgeCompiler
from openai_client import basic_chat

# --- 数据模型 ---

class StrategyDecision(BaseModel):
    status: str = Field(description="'need_more_evidence' 如果需要继续阅读正文/搜索；'ready' 仅当现有证据已能完美回答。")
    plan: str = Field(description="接下来的具体阅读或搜索计划")
    target_pages: List[Dict[str, Any]] = Field(default_factory=list, description="需补读的列表: [{'article_id': 'xxx', 'pages': [1,2,3]}]")

class VerificationResultLLM(BaseModel):
    status: str = Field(description="pass/fail")
    entity_name: str = Field(description="知识点名称")
    domain: str = Field(description="所属领域")
    refined_content: str = Field(description="核实后的精炼内容")

class WikiVerificationAgent:
    def __init__(self, db_path: str, table_prefix: str = "kb"):
        self.db_path = db_path
        self.prefix = table_prefix
        self.searcher = KnowledgeSearcher(db_path, table_prefix)
        self.compiler = DeepKnowledgeCompiler(db_path, table_prefix)
        self.client = basic_chat()
        
        # 加载模式文件
        guide_path = Path(__file__).parent / "WIKI_GUIDE.md"
        self.guide_content = guide_path.read_text(encoding="utf-8") if guide_path.exists() else "遵循严谨的 Wiki 维护规则。"

        # 初始化会话目录
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = Path("output/wiki_sessions") / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_path = self.session_dir / "evidence_board.md"
        self.evidence_path.write_text("# 证据看板 - 深度核实区\n", encoding="utf-8")

    def _append_evidence(self, title: str, content: str, article_id: str, page_no: Optional[int] = None):
        with open(self.evidence_path, "a", encoding="utf-8") as f:
            header = f"## 《{title}》"
            if page_no: header += f" - 第 {page_no} 页"
            f.write(f"\n{header} (ID: {article_id})\n")
            f.write(content + "\n---\n")

    async def chat_stream(self, user_query: str) -> AsyncIterator[str]:
        """主工作流：Wiki 检索 -> (多轮深度迭代) -> 最终合成"""
        
        # 1. Wiki 快速检索
        print("[*] 正在检索 Wiki 共识...")
        wiki_hits = self.searcher.search_wiki(user_query, limit=3)
        wiki_context = json.dumps(wiki_hits, ensure_ascii=False, indent=2)

        # 2. 初始文档检索 (FTS)
        print("[*] 正在初探文档库...")
        doc_hits = self.searcher.search_documents(user_query, limit=5)
        
        # 3. 深度迭代循环 (类似 v5 的核心逻辑)
        max_rounds = 3
        collected_ids = []
        
        for round_idx in range(max_rounds):
            evidence_context = self.evidence_path.read_text(encoding="utf-8")
            
            # 决策：是否需要读更多页码？
            print(f"[*] 迭代决策 [{round_idx+1}/{max_rounds}]...")
            decision_resp = self.client.basic_chat_with_structured_output(
                messages=[
                    {"role": "system", "content": "你是一个政策研究专家。请评估证据看板中的内容是否足以回答问题。如果需要精读具体文件的某些页码，请给出计划。"},
                    {"role": "user", "content": f"问题：{user_query}\n\n候选文档：{json.dumps(doc_hits, ensure_ascii=False)}\n\n当前看板证据：\n{evidence_context[:10000]}"}
                ],
                response_format=StrategyDecision
            )
            decision = decision_resp.choices[0].message.parsed
            
            if decision.status == "ready" and round_idx > 0:
                print("   [Ready] 证据已充足。")
                break
                
            if not decision.target_pages:
                # 初始迭代：如果没有指定，自动读前 2 页
                print("   [Action] 初始采集，读取相关文档首页...")
                for doc in doc_hits:
                    if doc['article_id'] not in collected_ids:
                        content = self.searcher.read_pages(doc['article_id'], [1, 2])
                        self._append_evidence(doc['title'], content, doc['article_id'])
                        collected_ids.append(doc['article_id'])
            else:
                # 按需补读
                for target in decision.target_pages:
                    aid = target.get('article_id')
                    pages = target.get('pages', [])
                    print(f"   [Action] 补读文档 {aid} 的第 {pages} 页...")
                    # 获取标题 (简单处理)
                    title = next((d['title'] for d in doc_hits if d['article_id'] == aid), aid)
                    content = self.searcher.read_pages(aid, pages)
                    self._append_evidence(title, content, aid)
                    if aid not in collected_ids: collected_ids.append(aid)

        # 4. 最终合成报告
        print("[*] 正在最终合成报告...")
        evidence_content = self.evidence_path.read_text(encoding="utf-8")
        
        system_prompt = f"""你是一个高级政策分析专家。请遵循【维护指南】：{self.guide_content}
要求：
1. 必须优先使用证据看板中的【原文】。
2. 引用时必须注明《文件全名》及页码。
3. 结论必须严谨，无证据不推论。"""

        user_prompt = f"问题：{user_query}\n\n【Wiki 存量信息】：\n{wiki_context}\n\n【最新证据看板】：\n{evidence_content}"

        full_response = ""
        response = self.client.basic_chat_with_tools(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            stream=True
        )

        for chunk in response:
            if hasattr(chunk, 'choices') and len(chunk.choices) > 0:
                content = chunk.choices[0].delta.content
                if content:
                    full_response += content
                    yield content

        # 5. 知识回流
        asyncio.create_task(self._verify_and_backflow(user_query, full_response, evidence_content, collected_ids))

    async def _verify_and_backflow(self, query: str, report: str, evidence: str, source_ids: List[str]):
        """审计并写回 Wiki (共识进化)"""
        del query  # 问题文本已被 report 和 evidence 吸收。
        print("\n[*] 正在启动知识回流核查...")
        try:
            resp = self.client.basic_chat_with_structured_output(
                messages=[
                    {"role": "system", "content": "你是一个审计员。请将报告中的核心政策结论提炼为 Wiki 条目内容。"},
                    {"role": "user", "content": f"报告内容：{report[:5000]}\n\n原文证据：{evidence[:10000]}"}
                ],
                response_format=VerificationResultLLM
            )
            res = resp.choices[0].message.parsed
            if res.status == "pass":
                print(f"   [Verified] 知识点 '{res.entity_name}' 正在进化 Wiki...")
                self.compiler.add_custom_synthesis(
                    entity_name=res.entity_name,
                    domain=res.domain or "深度提炼",
                    content=res.refined_content,
                    source_ids=source_ids
                )
        except Exception as error:  # pylint: disable=broad-exception-caught
            print(f"   [Error] 回流失败: {error}")

# --- 运行示例 ---
async def main():
    agent = WikiVerificationAgent("data/wiki_v4/wiki_v4.sqlite", "policy")
    query = "境外投资已纳税额如何抵扣？"
    print(f"\nUser Query: {query}\n" + "="*50)
    async for text in agent.chat_stream(query):
        print(text, end="", flush=True)
    print(f"\n\n[*] 会话存证至: {agent.evidence_path}")
    await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
