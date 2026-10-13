# XWiki 实现思路

## 公共边界

`XWikiService` 是入口，JSON CLI 调用同一服务。`MaintenanceTools` 为外部维护代理提供受校验的操作，自动维护循环自身不调用删除。调用方必须单独授权来源生命周期动作，不能把文档中的指令当成授权。

`db.py` 负责创建表和兼容升级。来源 ID 与内容哈希分开：ID 定位来源，哈希定位其内容版本。普通 Markdown 初始 ID 根据归档路径产生；自动维护来源可能采用内容派生 ID；显式更新始终保留已有 ID。因此不要把 ID 当成永远等于某种内容哈希的契约。

## 摄取和精确去重

`converter.py` 返回 `ParsedDocument` 与带定位的 `ParsedPage`；`documents.py` 提供可选二进制转换。Markdown/TXT 保留原有清理后 MD5 指纹；PDF/DOCX 用原始二进制 SHA256。指纹用于变化识别，不作为恶意输入的身份认证。

`service.ingest_inbox` 查询当前相同内容及旧版本快照。有效来源和相同处理版本可以跳过；失效、历史版本或需要刷新处理版本的输入保留并报告原因。归档采用临时文件、字节验证与替换，索引成功才移除未改变的收件箱输入。索引事务再次检查重复，阻止两个前置检查同时通过后产生重复记录。

`indexer.py` 可使用模型生成页摘要与元信息；没有凭据时生成确定性简短摘要。页摘要缓存键包括来源哈希、页号及实际处理版本；文档转换器版本纳入处理版本，避免升级转换器后重复使用旧摘要。

## 更新与删除

更新先验证输入位置、旧哈希和状态；随后解析、归档，再在索引事务中重验旧哈希。旧文档元数据、正文和可信定位保存到 `xwiki_source_versions`，事件保存到 `xwiki_source_events`。来源页、FTS5 和编译状态在同一事务内切换，关联文章任务进入审查。模型处理期间发生撤回时，最后提交被拒绝，输入保留。

`sources.py` 处理撤回、替代和删除。删除记录快照，移除当前页与 FTS5，保留 `deleted` 墓碑；旧引用因此无效。`mark_affected_pages` 将关联任务设为 `review` 并清除执行令牌。旧任务的完成回调只有匹配令牌才可写入，因此不能覆盖审查状态。

原文件及历史继续保留。数据库事务失败时索引和快照回滚；归档已先写入，失败可能留下无索引副本。系统没有承诺文件系统与数据库的跨资源原子性。详情见 [来源生命周期](source-lifecycle.md)。

## 文章写入与恢复

`entities.py` 校验来源是否有效、引用片段是否逐字存在、内容版本与可信定位是否匹配、页面关系是否合法。写入携带 `base_version`，旧版本拒绝；新建明确使用空基线。多篇文章的修改先验证，再事务写入数据库、保存修订并生成 Markdown。

外部改动的 Markdown 文件会触发冲突。一般异常会恢复已写文件并回滚数据库；机器断电需要结构检查恢复。回滚也是一次带版本和理由的新修订，旧快照中的失效来源不会绕过当前引用规则。

## 计划、证据与任务

`maintenance.py` 先用 `ReadPlan` 选择已有页面，再用 `MaintenancePlan` 提出操作。Pydantic 限制数量、长度和字段；一次选页 ID 错误允许有界纠正。代码检查已有事实及引用保留，并防止大量重复事实新建页。

`evidence.py` 将完全逐字支持与需要语义审查的转述分开。转述通过额外模型审查，但不能视为数学证明。任务保存计划和失败信息，超过重试阈值或发现需审查情况时进入 `review`。`MaintenanceQueue` 通过锁、指纹和执行令牌管理任务领取与完成，冷却只改变下一次运行时间。

## 检索和答案诊断

`searcher.py` 对文档使用 FTS5，失败或词法不足时使用回退；Wiki 对标题与正文做关键词匹配。检索结果检查来源状态、引用版本和审查状态；失效高排名文章不能挡住后续有效文章。`agent/query.py` 收集有界原文证据，生成回答并检查引用定位。DOCX 引用用 `s.N`，PDF/Markdown 页用 `p.N`。

诊断顺序是检查摄取结果、当前来源、候选排名、最终原文片段、生成结果和引用状态。检索未命中和模型读错证据分别记录，不能用一次答案错误直接归因于模型或向量缺失。

## 复现

```bash
python -m pip install ".[test,quality,documents,document-test]"
python -m pytest --cov=xwiki --cov-fail-under=80
python -m ruff check .
python -m mypy xwiki
python scripts/demo_wiki.py
python scripts/evaluate_wiki.py --output data/evaluation/offline.json
```

最后一条默认离线，只评估词法检索。真实模型评测需要显式 `--live` 和私有配置；只使用合成或明确授权资料。维护、持续维护和证据审查分别使用 `evaluate_maintenance.py`、`evaluate_continuous.py` 和 `evaluate_evidence.py`，各自参数见 `--help`。
