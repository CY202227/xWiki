"""Agent CLI stays explicit and returns structured outcomes."""

import json

from xwiki.__main__ import main


def test_default_cli_does_not_ingest(service, capsys):
    path = service.workspace.paths.inbox_dir / "pending.md"
    path.write_text("等待处理", encoding="utf-8")
    assert main(["--workspace", str(service.workspace.paths.root)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"]
    assert result["result"]["totals"]["documents"] == 0
    assert path.exists()


def test_cli_preview_update_and_conflict(service, capsys):
    payload = {"name": "概念", "content": "定义", "base_version": None, "reason": "创建"}
    path = service.workspace.paths.root / "change.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    prefix = ["--workspace", str(service.workspace.paths.root), "update", "--input", str(path)]
    assert main([*prefix, "--preview"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
    assert service.searcher.list_entities() == []
    assert main(prefix) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
    assert main(prefix) == 1
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "WikiConflictError"


def test_cli_invalid_update_returns_structured_error(service, capsys):
    path = service.workspace.paths.root / "bad-change.json"
    path.write_text(json.dumps({"name": 123, "content": "定义", "base_version": None, "reason": "创建"}), encoding="utf-8")
    assert main(["--workspace", str(service.workspace.paths.root), "update", "--input", str(path)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["type"] == "ValueError"
    assert service.searcher.list_entities() == []
