# SciFact 检索评测

来源：BEIR 的 SciFact 公开数据 https://github.com/beir-cellar/beir/wiki/Datasets-available 。
官方压缩包 https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip ，MD5 为 5f7d1de60b170fc8027bb7898e2efca1。
原数据、许可与科学事实验证任务见 https://github.com/allenai/scifact 。本仓库不重新分发语料。

复现：下载原压缩包后运行 `python scripts/evaluate_scifact.py /path/to/scifact.zip --out report.json`。
完整语料 5,183 篇，全部 300 个有标签测试查询；不筛掉难题，不按金标缩小语料。
标题与摘要直接写入 xWiki 检索数据库，用实际 query_documents 调用排名；摘要取正文前 500 字，不调用模型。
金标 qrels 只用于评分。语料、查询、报告含 SHA256，排序及各题排名均保存。

2026-10-12：Recall@1=0.5217、@5=0.7151、@10=0.7822、@20=0.8309，nDCG@10=0.6593，MRR@10=0.6270。
这是原始文档检索评测，不包括摄取解析、Wiki 编译、真实问答正确性或引用是否蕴含答案。
不能把这些数值当作科学声明正确率或 agent 产品评分。

`--live` 会额外用环境配置的模型回答固定前三题；记录引用状态或失败类型。
这只是有界功能试点，引用格式有效也不等于引用支持答案。模型别名不能证明背后实际模型身份。


2026-10-12 模型别名 odb 的固定三题试点：查询1和5生成格式有效引用，查询3超时。
这里只检查引用是否指向提供的证据；没有独立人工/模型判定答案是否被证据蕴含，不能报告66.7%答案正确率。
