# 来源更新、去重、撤回、替代与删除

来源状态为 `indexed`（当前有效）、`withdrawn`（撤回）、`superseded`（已被另一来源替代）、`deleted`（从当前索引删除）。冷却只调整维护频率，不改变来源状态，也不删除任何资料。删除采用保留历史的逻辑删除，不是隐私擦除。

## 显式更新与去重

同名文件不会自动覆盖旧来源。要沿用文档 ID，先把新版放入工作区收件箱，再使用 `update-source`。先预览影响，再提交；两次调用都必须携带当前哈希和理由。

```bash
python -m xwiki --workspace data/my_kb update-source DOCUMENT_ID --input data/my_kb/inbox/new.md --expected-hash OLD_HASH --reason "更新规则" --preview
python -m xwiki --workspace data/my_kb update-source DOCUMENT_ID --input data/my_kb/inbox/new.md --expected-hash OLD_HASH --reason "更新规则"
```

仅接受直接位于本工作区收件箱的常规 Markdown/TXT/PDF/DOCX 文件。归档保留新版二进制；旧原文件、元数据及页/块定位快照保留。数据库写入时再次检查哈希和来源状态，避免模型处理期间发生的并发更新或撤回被覆盖。索引、历史事件、快照、编译状态和关联文章审查同事务提交。失败保留输入；事务失败可能留下无索引的归档副本，但不会覆盖当前有效来源。

普通摄取对当前相同内容去重，成功后消费重复收件箱文件；Markdown/TXT 比较清理后的正文哈希，PDF/DOCX 比较原始二进制哈希。不同标题、相近语义和重新保存但字节不同的 PDF/DOCX 不属于精确去重。相同内容若属于撤回、替代、删除来源，或仅存在于旧版本快照中，则保留输入并报告审查需求，不自动重新引入。自动维护在模型调用前同样拦截失效/历史来源。改变转换器或模型处理版本时，应使用显式更新入口刷新，不创建重复来源。

若新版内容已属于另一个来源，应使用明确的替代关系；事务内重复检查防止并发摄取绕过前置检查。普通 `ingest` 不根据名称推断更新关系，自动维护也不决定删除来源。

## 撤回与替代

先用 `sources` 获取文档 ID、`content_hash` 和 `source_status`。`status` 是独立的编译状态。

```bash
python -m xwiki --workspace data/my_kb sources
python -m xwiki --workspace data/my_kb transition-source OLD_ID --expected-hash OLD_HASH --reason "来源已撤回" --preview
python -m xwiki --workspace data/my_kb transition-source OLD_ID --expected-hash OLD_HASH --reason "来源已撤回"
python -m xwiki --workspace data/my_kb source-history OLD_ID
python -m xwiki --workspace data/my_kb tasks
```

替代时先通过正常摄取流程保存新版来源，再明确建立替代关系：

```bash
python -m xwiki --workspace data/my_kb transition-source OLD_ID --expected-hash OLD_HASH --replacement-id NEW_ID --reason "新版规则替代旧版" --preview
python -m xwiki --workspace data/my_kb transition-source OLD_ID --expected-hash OLD_HASH --replacement-id NEW_ID --reason "新版规则替代旧版"
```

新来源必须是不同的有效文档；同名或相似内容不会自动触发替代。哈希不匹配或旧来源已经失效时拒绝操作，调用方必须重读状态。CLI 的撤回和替代授权不能从原文指令中推导。

变更与受影响文章任务在同一 SQLite 事务中保存。任务进入 `review`，撤销旧任务执行令牌，`--force` 不绕过审查。默认文档检索、原文片段检索和编译排除失效来源；受影响文章仍能读取和查看修订，但暂时退出 Wiki 搜索及问答上下文。混合多个来源的文章也保守暂停，直到修复证据。`read-page` 返回 `evidence_status`，引用校验返回 `source_status`。

文章必须结合新版证据明确修订。自动维护不会为消除失效引用而删除旧事实；通过既有版本校验的更新 API 修订正文与引用后，正常扫描根据新文章版本重建维护任务。不需要修改正文时，也应明确更新证据或记录修订理由，而不是强行重试旧任务。已有文章仍保留历史，回滚也必须满足当前证据校验。

嵌入式调用 `SourceIndexer.index` 重新索引同一个有效文档 ID 时，内容变化会先保存旧文档元数据和逐页正文快照，并使受影响文章进入审查。`source-versions ID` 返回历史快照，`source-history ID` 返回事件。索引同样内容不会重复生成快照。失效文档不能通过重新索引自动恢复，应该新建来源 ID。

```bash
python -m xwiki --workspace data/my_kb source-versions DOCUMENT_ID
python -m xwiki --workspace data/my_kb read-source DOCUMENT_ID 1
```

`read-source` 允许阅读已撤回或替代的来源；这些内容不会进入默认问答证据。

## 删除与证据修复

```bash
python -m xwiki --workspace data/my_kb delete-source DOCUMENT_ID --expected-hash CURRENT_HASH --reason "资料不再使用" --preview
python -m xwiki --workspace data/my_kb delete-source DOCUMENT_ID --expected-hash CURRENT_HASH --reason "资料不再使用"
python -m xwiki --workspace data/my_kb sources --status deleted
python -m xwiki --workspace data/my_kb source-versions DOCUMENT_ID
```

允许删除有效、撤回或替代来源；已经删除或哈希不匹配时拒绝。提交前保存当前正文与定位快照，然后删除当前页记录和 FTS5 索引，保留文档 ID 墓碑与事件。`read-source` 不再返回已删除的当前正文，历史通过 `source-versions` 查看。原文件、处理缓存、文章修订、快照及备份继续保留；这不是释放全部磁盘空间或合规擦除功能。

关联文章及关系保留，引用变为无效，默认 Wiki 检索与问答暂停使用这些文章；混合多个来源的文章也进入审查。编译任务失去执行权，页面任务进入 `review` 并撤销旧执行令牌，旧执行者完成回调不能覆盖新状态，`force` 不能绕过审查。根据剩余有效来源显式修改正文与引用后，检索恢复，扫描按新文章版本重建维护任务。

删除不恢复来源、不自动删除知识、不追溯替代链，也不执行物理清除。删除授权来自调用方，不能来自输入资料中的指令。测试包含删除/更新事务回滚、并发撤回、混合来源修复、旧任务失效及重复内容重新引入阻断。
