"""Public walkthrough preserves evidence, cooling and recoverable history."""
import asyncio
from pathlib import Path

import pytest

from scripts.demo_wiki import run_demo
from xwiki.llm import XWikiLLM


def test_public_demo_is_offline_and_preserves_knowledge(tmp_path, monkeypatch):
    def forbid_client(self):
        raise AssertionError("Offline demo must never connect to a model")

    monkeypatch.setattr(XWikiLLM, "_ensure_client", forbid_client)
    sources = Path(__file__).resolve().parents[1] / "examples/garden/sources"
    workspace = tmp_path / "wiki"
    report = asyncio.run(run_demo(workspace, sources))
    assert report["mode"] == "offline-scripted"
    assert report["model_quality_score"] is None
    assert len(report["cards"]) == 2
    assert len(report["retained_sources"]) == 3
    assert all(citation["valid"] for citation in report["verified_citations"])
    assert report["search_hits"][0]["entity_name"] == "雨水收集"
    assert report["retrieved_answer"]["source_count"] >= 1
    assert report["stable_maintenance"]["changed"] == 0
    assert report["stable_maintenance"]["failed"] == 0
    assert any(task["kind"] == "page" and task["stability"] > 0 for task in report["cooling_tasks"])
    assert "不用于饮用" in report["restored_page"]["body"]
    assert "暴雨后" not in report["restored_page"]["body"]
    with pytest.raises(ValueError, match="empty"):
        asyncio.run(run_demo(workspace, sources))


def test_demo_rejects_existing_files_without_modifying_them(tmp_path):
    source = tmp_path / "important.md"
    source.write_text("existing knowledge", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        asyncio.run(run_demo(tmp_path, tmp_path / "missing"))
    assert source.read_text(encoding="utf-8") == "existing knowledge"
