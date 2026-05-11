"""Workspace runtime state helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from .workspace import Workspace


@dataclass
class WorkspaceState:
  workspace: Workspace
  _data: Dict[str, Any] = field(default_factory=dict, init=False)

  def __post_init__(self) -> None:
    self._load()

  def _load(self) -> None:
    path = self.workspace.paths.status_file
    if not path.exists():
      self._data = {}
      return
    try:
      self._data = json.loads(path.read_text(encoding="utf-8"))
      if not isinstance(self._data, dict):
        self._data = {}
    except json.JSONDecodeError:
      self._data = {}

  def _save(self) -> None:
    self.workspace.paths.status_file.write_text(
        json.dumps(self._data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

  def get(self, key: str, default: Any = None) -> Any:
    return self._data.get(key, default)

  def set(self, key: str, value: Any) -> None:
    self._data[key] = value
    self._save()

  def set_document_status(
      self,
      document_id: str,
      status: str,
      note: Optional[str] = None,
  ) -> None:
    records = self._data.setdefault("documents", {})
    payload = {"status": status, "note": note}
    documents = records.setdefault(document_id, {})
    documents.update(payload)
    self._save()

  def get_document_status(self, document_id: str) -> Dict[str, Any] | None:
    return self._data.get("documents", {}).get(document_id)

  def clear(self) -> None:
    self._data = {}
    self._save()
