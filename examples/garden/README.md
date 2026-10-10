# 公开示例：虚构社区花园

三份原创合成资料，只有两个知识主题，包含用途限制、日常规则和后续补充。资料不含私人数据，不代表现实操作建议。

在仓库根目录运行，无需模型服务或密钥：

```bash
python -m pip install ".[test,quality]"
python scripts/demo_wiki.py
```

默认临时创建 Wiki，输出 `data/demo/report.json` 后清理临时空间。报告保留每轮维护计划、原文引用校验、检索证据、冷却任务和修订记录；临时路径随后不再有效。

保留可继续查看的 Wiki，必须选择空目录：

```bash
python scripts/demo_wiki.py --workspace data/garden-demo --output data/garden-demo-report.json
python -m xwiki --workspace data/garden-demo list
python -m xwiki --workspace data/garden-demo read-page 雨水收集
python -m xwiki --workspace data/garden-demo search 雨水收集
python -m xwiki --workspace data/garden-demo revisions 雨水收集
python -m xwiki --workspace data/garden-demo tasks
```

流程依次处理两个主题来源，再把第三份补充资料追加到已有雨水文章。稳定文章保持正文，通过 `next_due` 和 `stability` 降低维护频率。最后回滚雨水文章到补充前版本：三个来源仍保留，补充历史也仍可查阅。报告中的检索结果对应回滚前；`restored_page` 和最终目录对应回滚后。

维护器只按脚本复制来源原文、选择同名页面，不调用真实 LLM。它验证写入、引用、版本、冷却和回滚流程，不衡量模型选页、概括、证据判断或回答能力。离线问答仅返回证据，不生成答案。真实模型能力请另用 `scripts/evaluate_maintenance.py` 和 `scripts/evaluate_evidence.py`，阅读其 `--help` 后显式启用 live 模式。

重新演示请选择另一个空目录；脚本拒绝覆盖已有知识库。
