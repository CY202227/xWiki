"""Workspace layout helpers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class WorkspacePaths:
  """Standard directories for a single KB instance."""

  root: Path

  @property
  def inbox_dir(self) -> Path:
    return self.root / "inbox"

  @property
  def raw_dir(self) -> Path:
    return self.root / "raw"

  @property
  def wiki_dir(self) -> Path:
    return self.root / "wiki"

  @property
  def entity_dir(self) -> Path:
    return self.wiki_dir / "entities"

  @property
  def log_file(self) -> Path:
    return self.wiki_dir / "log.md"

  @property
  def report_dir(self) -> Path:
    return self.wiki_dir / "reports"

  @property
  def state_dir(self) -> Path:
    return self.root / ".xwiki"

  @property
  def schema_dir(self) -> Path:
    return self.state_dir / "schema"

  @property
  def session_dir(self) -> Path:
    return self.state_dir / "sessions"

  @property
  def db_path(self) -> Path:
    return self.state_dir / "xwiki.sqlite"

  @property
  def status_file(self) -> Path:
    return self.state_dir / "status.json"


class Workspace:
  """Create/resolve the xwiki workspace and provide stable helpers."""

  def __init__(self, root: str | Path):
    self.paths = WorkspacePaths(Path(root).expanduser().resolve())

  def ensure(self, clean_inbox: bool = False) -> None:
    for p in [
        self.paths.inbox_dir,
        self.paths.raw_dir,
        self.paths.wiki_dir,
        self.paths.entity_dir,
        self.paths.report_dir,
        self.paths.state_dir,
        self.paths.schema_dir,
        self.paths.session_dir,
    ]:
      p.mkdir(parents=True, exist_ok=True)
    self.paths.log_file.touch(exist_ok=True)
    self.paths.db_path.parent.mkdir(parents=True, exist_ok=True)
    if clean_inbox:
      for item in self.paths.inbox_dir.glob("*"):
        if item.is_file():
          item.unlink()
        elif item.is_dir():
          shutil.rmtree(item)

  def iter_inbox_files(self, allowed_exts: Iterable[str] | None = None):
    exts = {f".{ext.lstrip('.')}" for ext in (allowed_exts or {"md", "txt"})}
    for path in sorted(self.paths.inbox_dir.glob("*")):
      if path.is_file() and path.suffix.lower() in exts:
        yield path
