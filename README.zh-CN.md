# xWiki

[English](README.md) | 简体中文

XWiki 是由模型辅助维护的小型 Wiki，保留完整文章、可追溯证据和可恢复的历史。采用 [MIT 许可证](LICENSE)。

## 技术文档

- [产品范围与当前限制](docs/scope.md)
- [架构与运行路径](docs/architecture.md)
- [设计决策](docs/decisions.md)
- [可复现演示与截图](docs/verification.md)
- [文档摄取与多模态扩展方案](docs/document-ingestion-plan.md)
- [文本 PDF/DOCX 摄取与原始定位](docs/document-ingestion.md)
- [来源更新、去重与删除](docs/source-lifecycle.md)
- [技术方案](docs/technical-proposal.md)
- [实现流程](docs/implementation.md)

主要入口是 `XWikiService`，可供 FastAPI 后端、Notebook、任务运行器及其他宿主应用调用。

## 能力

- 服务接口统一提供摄取、编译、问答和检查。
- 每个工作区包含 `inbox/`、`raw/`、`wiki/` 和 `.xwiki/`；SQLite 位于 `{workspace}/.xwiki/xwiki.sqlite`。
- 文档使用 FTS5 和词法回退，Wiki 文章使用关键词检索；当前没有向量检索。
- 优先查询有效 Wiki，再按原文证据回答，并返回引用状态。
- 完整文章保留摘要、来源、关系、修订和回滚；摘要卡片用于发现文章，不替代全文。
- 支持结构检查和可选模型知识检查，以及有界的自动维护。

## 安装

需要 Python 3.10 或更高版本。在仓库根目录创建独立环境：

```bash
python -m venv .venv
# Windows PowerShell：.\.venv\Scripts\Activate.ps1
# macOS/Linux：source .venv/bin/activate
python -m pip install -e .
python -m xwiki --help
```

运行依赖与版本范围见 `pyproject.toml`。`constraints-tested.txt` 保存 Windows/Python 3.14 验证过的依赖快照，可用 `python -m pip install -c constraints-tested.txt -e ".[test,build]"` 复用；它不是通用跨平台锁文件。CI 按声明范围检查 Windows/Linux 的 Python 3.10、3.14。`python -m pip install -r requirements.txt` 仍可使用。

文本 PDF/DOCX 需要可选依赖：

```bash
python -m pip install -e ".[documents]"
```

基础运行只需要模型客户端、Schema 校验和环境配置依赖；浏览器自动化、HTTP 服务由宿主按需安装。测试用 `.[test]`，构建用 `.[build]` 和 `python -m build`。受管 Windows 若限制生成的命令入口，可使用 `python -m xwiki` 替代 `xwiki`。

安装包排除私人配置、运行知识库、评测输出与测试；源码包另含测试、合成资料和复现脚本。用 `python scripts/check_distributions.py dist` 审计发行内容。

在 `.env` 配置 `OPENAI_API_KEY`、`OPENAI_MODEL`（默认 `gpt-4.1`），以及可选的 `OPENAI_BASE_URL`。也支持 `llmAPI_KEY`、`API_BASE_URL`、`MODEL_NAME` 别名。无模型配置时可使用离线检索与证据读取，不能将其称为模型生成回答。

## 项目结构

```text
xwiki/
  service.py       # 公共服务入口
  config.py        # 配置
  converter.py     # 文本解析
  documents.py     # 可选 PDF/DOCX 转换
  indexer.py       # 来源索引
  searcher.py      # 检索
  agent/           # 编译、问答、检查与工具
scripts/           # 演示、检查与评测
tests/
```

## 快速开始

将资料放到 `data/my_kb/inbox/`，再运行：

```python
import asyncio
from xwiki import XWikiConfig, XWikiService


async def main() -> None:
    service = XWikiService(XWikiConfig(workspace="data/my_kb"))
    await service.ingest_inbox()
    await service.compile_knowledge()
    result = await service.ask("知识库的重点是什么？")
    print(result["answer"])


asyncio.run(main())
```

`python scripts/smoke_service.py` 提供冒烟检查。摄取先归档原文再索引，成功后才消费未改变的收件箱输入；失败输入保留。不支持的格式留在收件箱。`output_md/` 被 Git 忽略，仍可作为资料目录，使用前将文件复制进工作区收件箱。

文本 PDF 按真实物理页转换；DOCX 按正文段落或表格块定位，不伪造物理页码。图片、扫描或需 OCR 的内容拒绝并保留输入，详见文档摄取说明。支持 MarkItDown 不等于已接入其所有格式。

## CLI 与手动更新

默认命令只查看状态，不会自动摄取或编译：

```bash
python -m xwiki --workspace data/my_kb status
python -m xwiki --workspace data/my_kb ingest
python -m xwiki --workspace data/my_kb compile
python -m xwiki --workspace data/my_kb sources --status failed
python -m xwiki --workspace data/my_kb list --limit 20
python -m xwiki --workspace data/my_kb search "碳排放"
python -m xwiki --workspace data/my_kb search "碳排放" --kind documents
python -m xwiki --workspace data/my_kb read "碳排放"
python -m xwiki --workspace data/my_kb read-source DOCUMENT_ID 1 2
python -m xwiki --workspace data/my_kb update --input change.json --preview
python -m xwiki --workspace data/my_kb update --input change.json
python -m xwiki --workspace data/my_kb revisions "碳排放"
python -m xwiki --workspace data/my_kb lint
```

更新文件示例（引用须换成实际来源原文）：

```json
{
  "name": "碳排放",
  "content": "来源支持的定义与条件 [DOCUMENT_ID p.1]",
  "base_version": "VERSION_RETURNED_BY_READ",
  "reason": "根据新增来源补充适用条件",
  "domain": "环境",
  "attributes": {"适用条件": "原文支持的条件"},
  "sources": ["DOCUMENT_ID"],
  "citations": [
    {"document_id": "DOCUMENT_ID", "page_no": 1, "quote": "逐字原文片段"}
  ]
}
```

只有新建实体时使用 `base_version: null`；已有实体必须提供 `read` 返回的当前版本，旧版本拒绝。`--preview` 校验并返回差异，不写入实体或修订。回滚创建新修订，也重新校验引用：

```bash
python -m xwiki --workspace data/my_kb rollback "碳排放" REVISION_ID --base-version CURRENT_VERSION --reason "恢复经核验的旧版"
```

Python 对应接口为 `read_entity`、`update_entity`、`entity_revisions`、`rollback_entity`、`list_documents`；`MaintenanceTools` 提供宿主集成。CLI 返回包含 `ok` 及 `result` 或 `error` 的 JSON；摄取/编译批次失败返回非零退出码，并在 `stats.errors` 中列出错误。

SQLite 是权威存储，Markdown 是生成投影。外部修改会被保留并触发冲突，协调前不覆盖；`read` 返回 `external_markdown`，`lint` 报告差异。新文件名含身份指纹以避免冲突，未改动的旧投影首次更新保留原路径。

相同索引内容跳过；编译对相同内容及处理版本跳过，显式重建用 `compile --force`。文档的实体修改与完成状态一起保存，其他文档可在单项失败后继续处理。重复运行跳过，遗弃运行的领取状态一小时后过期。

生成知识要求有效的文档、定位与逐字引用；人工页面可以无证据开始，但检查会提示。引用存在不能证明每句结论正确。答案返回 `citation_status` 和警告，不自动回写 Wiki。来源数量按不同文档计数，中文词法和二元词回退不代表语义等价。

常规写入失败回滚数据库并恢复文件；进程突然退出仍可能使投影不同步，哈希检查用于发现它。实体上下文超过 120000 字符会明确失败，不静默丢弃证据。

## 完整文章与模型维护

```python
created = service.update_page(
    "雨水收集", "## 用途\n收集屋顶雨水。", summary="雨水收集的方法与维护",
    base_version=None, reason="建立文章",
)
page = service.read_page("雨水收集")  # 也可使用稳定页面 ID
cards = service.page_cards(limit=20)
links = service.page_links(page["page"]["id"])
```

关联页面用稳定 ID 的 `related` 列表指定。文章更新复用版本、引用、预览和修订校验；无变化不创建冗余版本。旧编译器仍可使用，完整文章维护流程使用 `maintain`。

```bash
python -m xwiki --workspace data/my_kb maintain --limit 2 --preview
python -m xwiki --workspace data/my_kb maintain --limit 2
python -m xwiki --workspace data/my_kb tasks
python -m xwiki --workspace data/my_kb read-page "雨水收集"
python -m xwiki --workspace data/my_kb write-page --input article.json --preview
```

`article.json` 使用 `title`、`body`、`summary`、`base_version`、`reason`，可加 `sources`、`citations`、`domain`、`related`。文章编辑预览不写文章；维护预览会调用模型并登记发现任务，但不归档输入、不保存文章，返回的是建议计划。

模型先看卡片、选最多五篇已有文章，再读全文和原文；每任务最多三个写操作、一个新文章。它决定是否保留来源以及新建或更新文章，不自动删除、合并或重命名。可只保留来源而不写文章；不保留的输入留在收件箱冷却，不物理删除。

自动维护保守保留旧事实和精确引用，允许标题、空白和格式变化；改写或删除旧事实会被拒绝。新冲突证据应与旧说法并列审查。文本规则可能拒绝安全转述，也不覆盖很短的句子，不是语义真值证明；明确纠正可走带版本的手动更新。新文章若至少 80% 的提取事实已存在则拒绝，用于近复制检测，不解决所有语义重复。选错页面 ID 只有一次纠正机会，再失败则不保存。

任务持久化到 SQLite。稳定检查延长间隔至最多七天，新内容重置冷却；新文章首次等待一小时。临时失败依次五分钟、十分钟重试，连续三次进入 `review`；非法计划、事实丢失、无效引用、重复页和输入缺失立即审查。领取一小时后过期。`--force` 可跳过冷却，但不绕过运行领取或审查。修正资料后用 `retry-task TASK_ID --fingerprint CURRENT_FINGERPRINT` 明确重试，重试仍重新生成并校验计划。

来源上下文上限 16000 字符，选定维护上下文上限 32000；超限明确失败，输入保留供拆分。发现阶段最多查看 50 个卡片和 10 个词法命中，适合小型 Wiki，不是全库穷举。没有后台守护进程，宿主自行调用维护；冷却期间仍可检索和读取。

显式配置真实模型检查：

```bash
python -m xwiki --env-file .env.test.local --workspace data/test_kb maintain
python scripts/smoke_maintenance.py --env-file .env.test.local
python scripts/smoke_maintenance.py --env-file .env.test.local --update
```

冒烟检查向模型发送合成资料，使用临时 Wiki，需显式运行，不属于单元测试。`--update` 检查增量更新保留旧事实。`XWIKI_LLM_MAX_OUTPUT_TOKENS` 默认4096；不支持 Schema 的兼容端点回退为 JSON 加本地校验，也可设 `XWIKI_STRUCTURED_MODE=json`。程序不能从模型别名推断参数规模；该流程不联系向量服务。

## 测试与评测

自动维护先验证引用文字，再审查正文、标题和摘要。审查者可看到每段引用附近最多300字符，远处条件可能仍被遗漏。逐字句子无需额外模型调用；转述与组合结论最多24个单位、24000字符，检查主体、数字、单位、否定、条件和例外。无依据结论、遗漏判断或无效证据使任务在写入前暂停，保存 `review_json` 与 `plan_json`。

语义审查仍是可误判的模型判断；手动编辑和旧编译器不使用该自动审核入口。引用定位修复只规范已提供的有效文档/页号，缺失引用不编造，未知 ID 与未提供页仍无效。

```bash
python scripts/evaluate_maintenance.py
python scripts/evaluate_evidence.py --env-file .env.test.local
python scripts/evaluate_continuous.py
python scripts/evaluate_wiki.py
python scripts/evaluate_wiki.py --live --env-file .env.test.local
python -m pytest
```

- 维护计划评测验证确定性写入规则，保存 `data/evaluation/maintenance-safety.json`。
- 证据评测测试受支持转述及错误数字、单位、禁止条件等，保存 `evidence-support.json`；接口/Schema 失败也计失败，不视为正确拒绝。
- 连续维护使用脚本计划运行25轮，测调度、事实保留、修订增长和错误恢复，不测真实模型理解质量。
- Wiki 评测使用小型合成中文资料；离线测 Hit@3 与倒数排名，真实模式另测答案关键词组和定位有效性，默认保存 `data/evaluation/latest.json`。无答案问题不进入检索/引用分母。关键词与定位分数不是全面语义准确率。

可用 `--dataset`、`--output` 比较固定资料和题集的多次结果；不能将不同指标混作总体质量。单元测试用临时工作区，不依赖私人知识库。

## 质量检查与公开演示

来源生命周期保留历史并追踪受影响文章，详见技术文档。[虚构社区花园](examples/garden/README.md)用原创合成资料离线演示摄取、增量维护、引用、检索、冷却和回滚，运行 `python scripts/demo_wiki.py` 保存 JSON。脚本模拟计划不代表真实模型成绩。

推送和 PR 的 CI 检查 Windows/Linux、Python3.10/3.14、最低80%语句覆盖率、Ruff、基础类型检查、发行内容及独立 wheel 安装。CI 无需模型密钥，真实评测单独运行。覆盖率不是知识正确率。

```bash
python -m pip install ".[test,quality,build]"
python -m ruff check xwiki scripts tests
python -m mypy
python -m pytest -q --cov=xwiki --cov-report=term-missing --cov-report=xml
python -m build
python scripts/check_distributions.py dist
```
