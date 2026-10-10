"""Primary importable facade for xWiki service usage."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import replace
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
from .entities import EntityStore


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
        self.entities = EntityStore(self.db, self.workspace)
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
        """Archive a verified copy; consume inbox only after successful indexing."""
        original = source.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        target = self.workspace.paths.raw_dir / f"{source.stem[:80]}-{digest[:16]}{source.suffix.lower()}"
        if target.is_symlink():
            raise ValueError("Archived source cannot be a symbolic link")
        if target.exists():
            if target.read_bytes() != original:
                raise ValueError("Archived source hash collision or external modification")
            return target
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(original)
            if temporary.read_bytes() != original:
                raise OSError("Source archive verification failed")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    async def ingest_inbox(self, clean_inbox: bool = False) -> ServiceResult:
        # Cleanup mode also preserves failed or unprocessed inputs.
        self.workspace.ensure()
        started = datetime.now().isoformat()
        files = list(self.workspace.iter_inbox_files({"md", "txt", "pdf", "docx"}))
        stats: dict[str, Any] = {"added": 0, "skipped": 0, "failed": 0, "errors": []}
        for file in files:
            if file.is_symlink():
                stats["skipped"] += 1
                continue
            try:
                initial = file.read_bytes()
                parsed = self.converter.parse_file(file)
                with self.db.connection() as conn:
                    duplicate = conn.execute(
                        "SELECT raw_path FROM xwiki_documents WHERE content_hash=? AND processor_version=?",
                        (parsed.content_hash, self.indexer.document_version(parsed)),
                    ).fetchone()
                if duplicate:
                    existing = Path(duplicate["raw_path"])
                    if existing.is_symlink() or not existing.is_file() or self.converter.parse_file(existing).content_hash != parsed.content_hash:
                        duplicate = None
                if duplicate:
                    stats["skipped"] += 1
                else:
                    raw = self._move_to_raw(file)
                    if raw.read_bytes() != initial:
                        raise ValueError("Archived bytes differ from the original input")
                    archived = replace(parsed, document_id=self.converter.build_document_id(raw), raw_path=raw)
                    if archived.content_hash != parsed.content_hash:
                        raise ValueError("Source changed while being archived")
                    await self.indexer.index(archived)
                    stats["added"] += 1
                if file.read_bytes() == initial:
                    file.unlink()
            except Exception as error:
                stats["failed"] += 1
                stats["errors"].append({"source": file.name, "error": str(error)})
        self.event_log.record(
            event_type="ingest_inbox",
            description=f"Ingested {stats.get('added', 0)} files",
            payload=stats,
        )
        return self._snapshot("ingest_inbox", started, stats)

    async def compile_knowledge(
        self, batch_size: Optional[int] = None, force: bool = False
    ) -> ServiceResult:
        started = datetime.now().isoformat()
        compiler = KnowledgeCompiler(
            db=self.db,
            workspace=self.workspace,
            llm=self.llm,
            batch_size=self.config.compile_batch_size if batch_size is None else batch_size,
            version=f"{self.config.processor_version}:{self.config.llm_model}",
        )
        stats = await compiler.run(force=force)
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

    def read_entity(self, name: str) -> dict:
        return self.entities.read(name)

    def read_page(self, page: str) -> dict:
        with self.db.connection() as conn:
            row = conn.execute("SELECT entity_name FROM xwiki_entities WHERE page_id=? OR entity_name=?", (page, page)).fetchone()
        if row is None:
            raise KeyError("Wiki page not found")
        result = self.entities.read(row[0])
        entity = result["entity"]
        result["page"] = {"id": entity["page_id"], "title": entity["entity_name"], "summary": entity["summary"] or entity["consensus_summary"][:300],
                          "body": entity["body"] or entity["consensus_summary"], "domain": entity["domain"]}
        evidence = self.searcher.get_entity_evidence(entity["entity_name"])
        result["evidence_status"] = "review_required" if evidence.get("source_issues") or any(not item["valid"] for item in evidence.get("citations", [])) else "valid" if evidence.get("citations") else "uncited"
        return result

    def update_page(self, title: str, body: str, *, summary: str, base_version: str | None, reason: str, **kwargs: Any) -> dict:
        return self.entities.update(title, summary or body[:300], body=body, summary=summary,
                                    base_version=base_version, reason=reason, **kwargs)

    def page_cards(self, domain: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
        return self.searcher.list_entities(domain, limit, offset)

    def page_links(self, page_id: str) -> dict:
        self.read_page(page_id)
        with self.db.connection() as conn:
            outgoing = [row[0] for row in conn.execute("SELECT target_id FROM xwiki_wiki_links WHERE source_id=? ORDER BY target_id", (page_id,))]
            incoming = [row[0] for row in conn.execute("SELECT source_id FROM xwiki_wiki_links WHERE target_id=? ORDER BY source_id", (page_id,))]
        return {"page_id": page_id, "outgoing": outgoing, "incoming": incoming}

    async def maintain(self, limit: int = 2, force: bool = False, preview: bool = False) -> dict:
        from .maintenance import WikiMaintainer
        return await WikiMaintainer(self).run(limit=limit, force=force, preview=preview)

    def maintenance_tasks(self, limit: int = 50) -> list[dict]:
        from .maintenance import MaintenanceQueue
        return MaintenanceQueue(self.db).list(limit)

    def retry_maintenance_task(self, task_id: int, fingerprint: str) -> dict:
        from .maintenance import MaintenanceQueue
        return MaintenanceQueue(self.db).retry(task_id, fingerprint)

    def list_documents(self, status: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
        self.searcher._validate_query("", limit)
        if offset < 0:
            raise ValueError("offset must be nonnegative")
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT d.document_id, d.title, d.raw_path, d.content_hash, d.status AS source_status, s.status, s.error "
                "FROM xwiki_documents d LEFT JOIN xwiki_compile_state s ON d.document_id=s.document_id "
                "WHERE (? IS NULL OR s.status=?) ORDER BY d.document_id LIMIT ? OFFSET ?",
                (status, status, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def transition_source(self, document_id: str, **kwargs: Any) -> dict:
        from .sources import SourceLifecycle
        return SourceLifecycle(self.db).transition(document_id, **kwargs)

    def source_history(self, document_id: str) -> list[dict]:
        from .sources import SourceLifecycle
        return SourceLifecycle(self.db).history(document_id)

    def source_versions(self, document_id: str) -> list[dict]:
        from .sources import SourceLifecycle
        return SourceLifecycle(self.db).versions(document_id)

    def update_entity(self, name: str, content: str, **kwargs: Any) -> dict:
        """Create/update with base_version, reason, optional citations and preview."""
        return self.entities.update(name, content, **kwargs)

    def entity_revisions(self, name: str, limit: int = 20) -> list[dict]:
        return self.entities.revisions(name, limit)

    def rollback_entity(self, name: str, revision_id: int, **kwargs: Any) -> dict:
        return self.entities.rollback(name, revision_id, **kwargs)

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
                "documents": conn.execute(
                    "SELECT COUNT(*) FROM xwiki_documents"
                ).fetchone()[0],
                "entities": conn.execute(
                    "SELECT COUNT(*) FROM xwiki_entities"
                ).fetchone()[0],
                "events": conn.execute("SELECT COUNT(*) FROM xwiki_events").fetchone()[
                    0
                ],
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
