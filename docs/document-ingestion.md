# PDF/DOCX 摄取

文本 PDF 与 DOCX 正文已通过本地 MarkItDown 接入。扫描页、图片和多模态 OCR 尚未接入；检测到图片或空转换时明确失败并保留收件箱。

```bash
python -m pip install ".[documents]"
# 将 PDF/DOCX 放入工作区 inbox，再运行：
python -m xwiki --workspace data/my_kb ingest
python -m xwiki --workspace data/my_kb sources
python -m xwiki --workspace data/my_kb search Quasar --kind documents
python -m xwiki --workspace data/my_kb read-source DOCUMENT_ID 1 2
```

默认 Markdown/TXT 路径无需文档依赖。未安装 extras 时，任务返回安装说明，不消费输入。`maintain` 也识别 PDF/DOCX，但来源预算仍为 16,000 字符，大文件需先分拆或走摄取与显式选页。

## 真实定位

PDF 按物理页分离，再逐页转换，保留真实页码与 `locator.kind=pdf_page`；引用使用 `[document_id p.N]`。

DOCX 按主文档正文段落/表格块转换，保留块编号、块类型及 `locator.kind=docx_block`；引用使用 `[document_id s.N]`。空段落可能产生编号间隙，编号不是物理页码或全局段落序号。`read-source ID N` 保留整数参数，输出标签明确标注 DOCX 块位置。页脚、页眉、脚注、批注、浮动内容及复杂修订目前没有完整定位支持。

引用定位从索引记录填充。模型提交不匹配的定位元数据时保存失败。已验证引用可从误用的 `p.N` 规范化为 `s.N`，只修正定位格式。正文、原始文件指纹、转换器版本和定位元数据存于 SQLite；原始二进制保存在 raw 目录。

## 预算与边界

- 原始文件最多 32 MiB。
- PDF 最多 200 页，禁止加密 PDF；空白页也要求审查。
- DOCX 最多 200 个正文段落/表格块，解压内容最多 128 MiB。
- 转换正文最多 200 万字符。
- 插件禁用，不配置模型客户端，只提供本地二进制流。

这些是数量限制，不是硬超时或操作系统沙箱。复杂文档的生产处理仍需独立进程和资源隔离。逐字引用针对提取文本，不承诺与二进制字节或视觉排版完全一致。

## 验证

```bash
python -m pip install ".[test,quality,documents,document-test]"
python -m pytest tests/test_documents.py -q
```

测试现场生成原创 PDF/DOCX，验证数字与否定、页码、表格、二进制归档、去重、定位防伪、错误保留和本地转换无网络访问。视觉解析见 [后续方案](document-ingestion-plan.md)。
