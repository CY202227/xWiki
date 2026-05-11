"""Primary importable facade for xWiki service usage."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .agent.compiler import KnowledgeCompiler
from .agent.linter import KnowledgeLinter
from .agent.query import QueryEngine
from .config import XWikiConfig
from .converter import MarkdownConverter
from .db import XWikiDatabase
from .indexer import SourceIndexer
from .llm import XWikiLLM
from .lint import StructuralLinter
from .log import XWikiEventLog
from .schema import ensure_contract_files
from .searcher import XWikiSearcher
from .state import WorkspaceState
from .workspace import Workspace


@dataclass(frozen=True)
class ServiceResult:
  started_at: str
  finished_at: str
  operation: str
  stats: Dict[str, Any]


class XWikiService:
  def __init__(
      self,
      config: XWikiConfig | None = None,
      workspace: str | Path | Workspace | None = None,
  ) -> None:
    if isinstance(workspace, Workspace):
      self.workspace = workspace
      cfg = config or XWikiConfig(workspace=str(workspace.paths.root))
    else:
      cfg = config or XWikiConfig(workspace=str(workspace or "data/my_kb"))
      self.workspace = Workspace(cfg.resolve_workspace())
    self.config = cfg
    self.workspace.ensure()
    ensure_contract_files(self.workspace.paths.schema_dir)
    self.db = XWikiDatabase(self.workspace.paths.db_path)
    self.db.bootstrap()
    self.state = WorkspaceState(self.workspace)
    self.llm = XWikiLLM(self.config)
    self.event_log = XWikiEventLog(self.db, self.workspace.paths.log_file)
    self.searcher = XWikiSearcher(self.db)
    self.converter = MarkdownConverter()
    self.indexer = SourceIndexer(
        converter=self.converter,
        db=self.db,
        llm=self.llm,
        state=self.state,
        config=self.config,
    )

  @classmethod
  def from_dir(cls, workspace: str | Path, **kwargs: Any) -> "XWikiService":
    return cls(workspace=workspace, **kwargs)

  def _snapshot(
      self, operation: str, started: str, stats: Dict[str, Any]
  ) -> ServiceResult:
    return ServiceResult(
        started_at=started,
        finished_at=datetime.now().isoformat(),
        operation=operation,
        stats=stats,
    )

  def _move_to_raw(self, source: Path) -> Path:
    target = self.workspace.paths.raw_dir / source.name
    if target.exists():
      target = self.workspace.paths.raw_dir / f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{source.name}"
    shutil.move(str(source), target)
    return target

  async def ingest_inbox(self, clean_inbox: bool = False) -> ServiceResult:
    self.workspace.ensure(clean_inbox=clean_inbox)
    started = datetime.now().isoformat()
    files = list(self.workspace.iter_inbox_files({"md", "txt"}))
    parsed_docs = []
    for file in files:
      raw = self._move_to_raw(file)
      parsed_docs.append(self.converter.parse_file(raw))
    stats = await self.indexer.index_all(parsed_docs)
    self.event_log.record(
        event_type="ingest_inbox",
        description=f"Ingested {stats.get('added', 0)} files",
        payload=stats,
    )
    return self._snapshot("ingest_inbox", started, stats)

  async def compile_knowledge(self, batch_size: Optional[int] = None) -> ServiceResult:
    started = datetime.now().isoformat()
    compiler = KnowledgeCompiler(
        db=self.db,
        workspace=self.workspace,
        llm=self.llm,
        batch_size=batch_size or self.config.compile_batch_size,
    )
    stats = await compiler.run()
    self.event_log.record(
        event_type="compile_knowledge",
        description=(
            f"documents={stats.get('documents_seen', 0)}, compiled={stats.get('compiled', 0)}"
        ),
        payload=stats,
    )
    return self._snapshot("compile_knowledge", started, stats)

  async def ask(self, question: str, backflow: bool = False) -> Dict[str, Any]:
    engine = QueryEngine(searcher=self.searcher, llm=self.llm)
    return await engine.ask(question=question, backflow=backflow)

  def query_documents(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    return self.searcher.search_documents(query, limit=limit)

  def query_wiki(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    return self.searcher.search_wiki(query, limit=limit)

  def run_structural_lint(self) -> Dict[str, Any]:
    linter = StructuralLinter(self.db, self.workspace.paths.report_dir)
    result = linter.run()
    filename = f"structural_lint_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    self.event_log.append_report(result, filename)
    self.event_log.record("structural_lint", "run finished", result)
    return result

  async def run_knowledge_lint(self) -> Dict[str, Any]:
    linter = KnowledgeLinter(self.llm, self.db)
    report = {
        "contradictions": await linter.check_contradictions(),
        "quality": await linter.check_quality(),
    }
    filename = f"knowledge_lint_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    self.event_log.append_report(report, filename)
    self.event_log.record("knowledge_lint", "run finished", report)
    return report

  def status(self) -> Dict[str, Any]:
    with self.db.connection() as conn:
      totals = {
          "documents": conn.execute("SELECT COUNT(*) FROM xwiki_documents").fetchone()[0],
          "entities": conn.execute("SELECT COUNT(*) FROM xwiki_entities").fetchone()[0],
          "events": conn.execute("SELECT COUNT(*) FROM xwiki_events").fetchone()[0],
      }
    return {
        "workspace": str(self.workspace.paths.root),
        "totals": totals,
        "recent": self.searcher.get_recent_activity(10),
      }

  def run_smoke(self) -> Dict[str, Any]:
    return {
        "status": self.status(),
        "overview": self.searcher.get_overview(),
    }
