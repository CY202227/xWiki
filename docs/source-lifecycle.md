# 来源更新、撤回与替代

来源有三个状态：`indexed`（当前有效）、`withdrawn`（撤回）、`superseded`（已被另一来源替代）。冷却只调整维护频率，不改变来源状态，也不删除任何资料。

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

`read-source` 是明确的历史查阅入口，仍允许阅读已撤回的来源；这些内容不会进入默认问答证据。撤回不是隐私擦除，不删除原始文件、数据库正文、快照或备份。当前没有恢复来源、物理清除、自动合并或自动追溯替代链的功能。
