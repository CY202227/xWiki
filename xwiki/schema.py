"""Default machine-contract files for the KB workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

AGENTS_MD = """# XWiki AGENTS\n\n""".strip()

SCHEMA_FILES: Dict[str, str] = {
    "AGENTS.md": """
# XWiki Workspace Contract\n
本项目用于结构化维持知识仓：\n- 以 `inbox/` 接收待处理原文。\n- 成功入库后转入 `raw/`。\n- 由服务编译为 `wiki/entities/*.md`。\n- `.xwiki/` 存运行状态与事件。\n""".strip(),
    "page_types.md": """
# Page Types\n\n- concept: 实体定义页\n- policy: 政策、规范、规则\n- method: 方法与流程\n""".strip(),
    "ingest_workflow.md": """
# Ingest Workflow\n\n1. `inbox/` 放新文件。\n2. 调用 `ingest_inbox()`。\n3. 文件入 `raw/` 并持久化文档与分页。\n4. 触发 `compile_knowledge()`。\n""".strip(),
    "citation_style.md": """
# Citation Style\n\n所有事实必须可回溯到 source document，回复时附带 `document_id` 和页码。\n""".strip(),
    "lint_workflow.md": """
# Lint Workflow\n\n- 结构检查：缺失实体页、孤儿实体、陈旧实体。\n- 语义检查：LLM 抽样识别冲突与断言问题。\n""".strip(),
}


def ensure_contract_files(schema_dir: Path) -> None:
    schema_dir.mkdir(parents=True, exist_ok=True)
    for name, text in SCHEMA_FILES.items():
        path = schema_dir / name
        if not path.exists():
            path.write_text(text + "\n", encoding="utf-8")
