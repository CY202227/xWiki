"""Run the public offline demo and render a shareable evidence report."""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.demo_wiki import run_demo


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="data/demo-docs")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="xwiki-docs-") as directory:
        report = asyncio.run(run_demo(Path(directory), root / "examples/garden/sources"))
    public = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": report["mode"], "model_quality_score": None,
        "command": "python scripts/render_demo_report.py --output-dir docs/assets",
        "stages": [{"source": stage["source"], "processed": stage["maintenance"]["processed"],
                    "changed": stage["maintenance"]["changed"], "failed": stage["maintenance"]["failed"]} for stage in report["stages"]],
        "article_count": len(report["cards"]), "source_count": len(report["retained_sources"]),
        "valid_citations": sum(citation["valid"] for citation in report["verified_citations"]),
        "citation_count": len(report["verified_citations"]),
        "stable_changes": report["stable_maintenance"]["changed"],
        "cooling_pages": [{"stability": task["stability"], "status": task["status"]} for task in report["cooling_tasks"] if task["kind"] == "page"],
        "restored_page": report["restored_page"],
        "revision_count_before_rollback": len(report["revisions_before_rollback"]),
        "retrieved_sources_before_rollback": report["retrieved_answer"]["source_count"],
        "limitations": report["limitations"],
    }
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "demo-report.json").write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = "".join(f"<tr><td>{html.escape(stage['source'])}</td><td>{stage['changed']}</td><td>{stage['failed']}</td></tr>" for stage in public["stages"])
    body = html.escape(public["restored_page"]["body"])
    document = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>XWiki · 实际执行报告</title>
<style>body{{font:16px/1.6 system-ui,'Microsoft YaHei',sans-serif;margin:40px auto;max-width:1000px;color:#17232b;background:#fff}}h1{{font-size:28px;margin-bottom:6px}}h2{{font-size:20px}}.note{{border-left:4px solid #547681;padding:12px 20px;background:#f2f5f6}}.metrics{{display:flex;gap:48px;margin:28px 0}}.metrics strong{{display:block;font-size:30px}}table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #cbd4d8;padding:10px;text-align:left}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7f8;padding:20px;font-size:14px}}small{{color:#4b5962}}</style>
<h1>XWiki · 实际执行报告</h1><small>原创合成资料 · {html.escape(public['generated_at_utc'])} · offline-scripted</small>
<p class="note">离线脚本模拟维护计划，验证引用、修订与冷却流程。未调用真实模型，未生成模型质量分数。这是执行报告，不是产品 Web 界面。</p>
<div class="metrics"><div><strong>{public['article_count']}</strong>篇完整文章</div><div><strong>{public['source_count']}</strong>份保留来源</div><div><strong>{public['valid_citations']}/{public['citation_count']}</strong>有效引用</div><div><strong>{public['stable_changes']}</strong>次稳定页面改写</div></div>
<h2>实际维护步骤</h2><table><tr><th>来源</th><th>文章变更</th><th>失败</th></tr>{rows}</table>
<p>回滚前：{public['revision_count_before_rollback']} 个雨水文章修订，问答检索到 {public['retrieved_sources_before_rollback']} 份来源。回滚后仍保留 {public['source_count']} 份来源。</p>
<h2>回滚后的正文</h2><pre>{body}</pre>
<h2>复现命令</h2><pre>{html.escape(public['command'])}</pre><small>对应原始数据：demo-report.json；模型能力需另行执行真实模型评测。</small></html>"""
    (output / "demo-report.html").write_text(document, encoding="utf-8")
    print(json.dumps({"ok": True, "output_dir": str(output.resolve()), "mode": public["mode"]}))


if __name__ == "__main__":
    main()
