"""Validated entity changes, optimistic versions, and revision history."""

from __future__ import annotations

import difflib
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .db import XWikiDatabase
from .files import atomic_write
from .models import SourceCitation
from .renderer import entity_file_name, render_entity_markdown, _slugify
from .workspace import Workspace


class WikiConflictError(ValueError):
    """The page or its Markdown changed since the caller read it."""


def entity_version(entity: dict | None) -> str | None:
    if entity is None:
        return None
    payload = json.dumps(entity, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class EntityStore:
    def __init__(self, db: XWikiDatabase, workspace: Workspace):
        self.db = db
        self.workspace = workspace

    def read(self, name: str) -> dict:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Entity name must be a nonempty string")
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM xwiki_entities WHERE entity_name = ?", (name,)).fetchone()
        if row is None:
            raise KeyError(f"Entity not found: {name}")
        entity = dict(row)
        with self.db.connection() as conn:
            tracked = conn.execute("SELECT * FROM xwiki_entity_files WHERE entity_name=?", (name,)).fetchone()
        result = {"entity": entity, "version": entity_version(entity), "markdown": render_entity_markdown(entity), "file_modified": False}
        if tracked:
            path = self.workspace.paths.entity_dir / tracked["relative_path"]
            if path.is_symlink() or path.resolve().parent != self.workspace.paths.entity_dir.resolve():
                raise WikiConflictError("Entity file must stay inside the entity directory")
            if path.exists():
                text = path.read_text(encoding="utf-8")
                result["file_modified"] = hashlib.sha256(text.encode("utf-8")).hexdigest() != tracked["content_hash"]
                if result["file_modified"]:
                    result["external_markdown"] = text
        return result

    def revisions(self, name: str, limit: int = 20) -> list[dict]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM xwiki_entity_revisions WHERE entity_name = ? ORDER BY id DESC LIMIT ?",
                (name, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def _validate(self, conn, entity: dict) -> dict:
        entity = dict(entity)
        if not entity.get("page_id"):
            entity["page_id"] = uuid.uuid5(uuid.NAMESPACE_URL, 'xwiki:' + entity["entity_name"]).hex
        entity.setdefault("summary", "")
        entity.setdefault("body", "")
        entity.setdefault("related_json", "[]")
        if not isinstance(entity["body"], str) or not isinstance(entity["summary"], str) or len(entity["summary"]) > 500:
            raise ValueError("Body must be text and summary must not exceed 500 characters")
        related = json.loads(entity["related_json"])
        if not isinstance(related, list) or any(not isinstance(item, str) for item in related):
            raise ValueError("Related pages must be a list of page IDs")
        for page_id in related:
            if page_id == entity["page_id"] or not conn.execute("SELECT 1 FROM xwiki_entities WHERE page_id=?", (page_id,)).fetchone():
                raise ValueError("Related pages must exist and cannot refer to the same page")
        name = entity.get("entity_name")
        content = entity.get("consensus_summary")
        if not isinstance(name, str) or not isinstance(content, str) or not name.strip() or not content.strip():
            raise ValueError("Entity name and content must be nonempty")
        if not isinstance(entity.get("domain"), str):
            raise ValueError("Entity domain must be a string")
        attributes = json.loads(entity.get("attributes_json", "{}"))
        if not isinstance(attributes, dict):
            raise ValueError("attributes_json must contain an object")
        sources = json.loads(entity.get("source_links_json", "[]"))
        if not isinstance(sources, list) or any(not isinstance(item, str) for item in sources):
            raise ValueError("source_links_json must contain document IDs")
        sources = list(dict.fromkeys(sources))
        for source in sources:
            if conn.execute("SELECT 1 FROM xwiki_documents WHERE document_id = ? AND status='indexed'", (source,)).fetchone() is None:
                raise ValueError(f"Unknown source: {source}")
        citations = []
        citation_items = json.loads(entity.get("citations_json", "[]"))
        if not isinstance(citation_items, list):
            raise ValueError("citations_json must contain a list")
        for item in citation_items:
            citation = SourceCitation.model_validate(item)
            if citation.document_id not in sources:
                raise ValueError("Citation must refer to a declared source")
            page = conn.execute(
                "SELECT p.content, d.content_hash FROM xwiki_pages p "
                "JOIN xwiki_documents d ON p.document_id = d.document_id "
                "WHERE p.document_id = ? AND p.page_no = ?",
                (citation.document_id, citation.page_no),
            ).fetchone()
            if page is None or not citation.quote.strip() or citation.quote not in page["content"]:
                raise ValueError("Citation page or verbatim quote does not match the source")
            if citation.content_hash and citation.content_hash != page["content_hash"]:
                raise ValueError("Citation source changed; reread the source")
            citation.content_hash = page["content_hash"]
            payload = citation.model_dump()
            if payload not in citations:
                citations.append(payload)
        entity["source_links_json"] = json.dumps(sources, ensure_ascii=False)
        entity["citations_json"] = json.dumps(citations, ensure_ascii=False)
        return entity

    def _target(self, conn, entity: dict, previous: dict | None) -> Path:
        root = self.workspace.paths.entity_dir.resolve()
        tracked = conn.execute("SELECT * FROM xwiki_entity_files WHERE entity_name = ?", (entity["entity_name"],)).fetchone()
        target = root / (tracked["relative_path"] if tracked else entity_file_name(entity["entity_name"]))
        if not tracked:
            legacy = root / f"{_slugify(entity['entity_name'])}.md"
            if legacy.exists():
                target = legacy
        if target.is_symlink() or target.resolve().parent != root:
            raise WikiConflictError("Entity file must stay inside the entity directory")
        if target.exists():
            text = target.read_text(encoding="utf-8")
            if tracked:
                if hashlib.sha256(text.encode("utf-8")).hexdigest() != tracked["content_hash"]:
                    raise WikiConflictError("Markdown was edited externally; reconcile it before updating")
            elif previous:
                expected = render_entity_markdown(previous)
                legacy_expected = expected
                for key, field in (("title", "entity_name"), ("domain", "domain"), ("updated_at", "updated_at")):
                    legacy_expected = legacy_expected.replace(
                        f"{key}: {json.dumps(previous.get(field, ''), ensure_ascii=False)}",
                        f"{key}: {previous.get(field, '')}", 1,
                    )
                if text not in (expected, legacy_expected):
                    raise WikiConflictError("Existing Markdown differs from the saved entity")
            else:
                raise WikiConflictError("Entity filename already exists")
        return target

    def apply(self, changes: list[dict], reason: str, *, preview: bool = False, finalize=None) -> list[dict]:
        """Apply a complete change set; restore files if a normal write fails.

        SQLite remains authoritative. Crash-time file drift is detected on the
        next change rather than silently overwriting an inconsistent projection.
        """
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A change reason is required")
        originals = []
        results = []
        with self.db.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                names = set()
                prepared = []
                for change in changes:
                    incoming = change["entity"]
                    name = incoming["entity_name"]
                    if name in names:
                        raise ValueError("Duplicate entity in change set")
                    names.add(name)
                    row = conn.execute("SELECT * FROM xwiki_entities WHERE entity_name = ?", (name,)).fetchone()
                    previous = dict(row) if row else None
                    entity = self._validate(conn, {**(previous or {}), **incoming})
                    if previous and entity["page_id"] != previous["page_id"]:
                        raise ValueError("Page ID cannot change")
                    if change.get("base_version") != entity_version(previous):
                        raise WikiConflictError("Entity changed since it was read; refresh the version")
                    target = self._target(conn, entity, previous)
                    fields = ("entity_name", "domain", "consensus_summary", "attributes_json", "source_links_json", "citations_json", "page_id", "summary", "body", "related_json")
                    unchanged = previous is not None and all(
                        (json.loads(entity[key]) == json.loads(previous[key]) if key.endswith("_json") else entity[key] == previous[key])
                        for key in fields
                    )
                    if unchanged and target.exists():
                        results.append({"entity_name": name, "version": entity_version(previous), "path": str(target), "diff": "", "changed": False})
                        continue
                    entity["created_at"] = previous["created_at"] if previous else datetime.now(timezone.utc).isoformat()
                    entity["updated_at"] = datetime.now(timezone.utc).isoformat()
                    text = render_entity_markdown(entity)
                    before = target.read_text(encoding="utf-8") if target.exists() else ""
                    result = {"entity_name": name, "version": entity_version(entity), "path": str(target), "changed": True,
                              "diff": "".join(difflib.unified_diff(before.splitlines(True), text.splitlines(True), fromfile="before", tofile="after"))}
                    results.append(result)
                    prepared.append((entity, previous, target, text))
                if preview:
                    conn.rollback()
                    return results
                for entity, previous, target, text in prepared:
                    name = entity["entity_name"]
                    if previous and not conn.execute("SELECT 1 FROM xwiki_entity_revisions WHERE entity_name = ?", (name,)).fetchone():
                        conn.execute("INSERT INTO xwiki_entity_revisions (entity_name, snapshot_json, reason, created_at) VALUES (?, ?, ?, ?)",
                                     (name, json.dumps(previous, ensure_ascii=False), "Baseline before first revision", entity["updated_at"]))
                    conn.execute(
                        "INSERT INTO xwiki_entities (entity_name, domain, consensus_summary, attributes_json, source_links_json, updated_at, created_at, citations_json, page_id, summary, body, related_json) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(entity_name) DO UPDATE SET "
                        "domain=excluded.domain, consensus_summary=excluded.consensus_summary, attributes_json=excluded.attributes_json, "
                        "source_links_json=excluded.source_links_json, updated_at=excluded.updated_at, citations_json=excluded.citations_json, "
                        "page_id=excluded.page_id, summary=excluded.summary, body=excluded.body, related_json=excluded.related_json",
                        tuple(entity[key] for key in ("entity_name", "domain", "consensus_summary", "attributes_json", "source_links_json", "updated_at", "created_at", "citations_json", "page_id", "summary", "body", "related_json")),
                    )
                    conn.execute("DELETE FROM xwiki_wiki_links WHERE source_id=?", (entity["page_id"],))
                    conn.executemany("INSERT INTO xwiki_wiki_links VALUES (?, ?)", [(entity["page_id"], target) for target in json.loads(entity["related_json"])])
                    conn.execute("DELETE FROM xwiki_entity_links WHERE entity_name = ?", (name,))
                    conn.executemany("INSERT INTO xwiki_entity_links VALUES (?, ?)", [(name, doc) for doc in json.loads(entity["source_links_json"])])
                    conn.execute("INSERT INTO xwiki_entity_revisions (entity_name, snapshot_json, reason, created_at) VALUES (?, ?, ?, ?)",
                                 (name, json.dumps(entity, ensure_ascii=False), reason, entity["updated_at"]))
                    originals.append((target, target.read_text(encoding="utf-8") if target.exists() else None))
                    atomic_write(target, text)
                    conn.execute("INSERT INTO xwiki_entity_files VALUES (?, ?, ?) ON CONFLICT(entity_name) DO UPDATE SET relative_path=excluded.relative_path, content_hash=excluded.content_hash",
                                 (name, target.name, hashlib.sha256(text.encode("utf-8")).hexdigest()))
                if finalize:
                    finalize(conn)
                conn.commit()
            except BaseException:
                conn.rollback()
                for target, original_text in reversed(originals):
                    if original_text is None:
                        target.unlink(missing_ok=True)
                    else:
                        atomic_write(target, original_text)
                raise
        return results

    def update(self, name: str, content: str, *, base_version: str | None, reason: str,
               domain: str | None = None, attributes: dict | None = None,
               sources: list[str] | None = None, citations: list[dict] | None = None, preview: bool = False,
               body: str | None = None, summary: str | None = None, related: list[str] | None = None) -> dict:
        try:
            entity = self.read(name)["entity"]
        except KeyError:
            entity = {"entity_name": name, "domain": "未分类", "attributes_json": "{}", "source_links_json": "[]", "citations_json": "[]"}
        entity["consensus_summary"] = content
        for field, value in (("domain", domain), ("attributes_json", attributes), ("source_links_json", sources), ("citations_json", citations),
                             ("body", body), ("summary", summary), ("related_json", related)):
            if value is not None:
                entity[field] = value if field in ("domain", "body", "summary") else json.dumps(value, ensure_ascii=False)
        return self.apply([{"entity": entity, "base_version": base_version}], reason, preview=preview)[0]

    def rollback(self, name: str, revision_id: int, *, base_version: str, reason: str) -> dict:
        with self.db.connection() as conn:
            row = conn.execute("SELECT snapshot_json FROM xwiki_entity_revisions WHERE entity_name = ? AND id = ?", (name, revision_id)).fetchone()
        if row is None:
            raise KeyError("Revision not found")
        snapshot = json.loads(row[0])
        for key, value in (("body", ""), ("summary", ""), ("related_json", "[]")):
            snapshot.setdefault(key, value)
        return self.apply([{"entity": snapshot, "base_version": base_version}], reason)[0]
