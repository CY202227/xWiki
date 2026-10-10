"""Tool functions consumed by query/compiler agents."""

from __future__ import annotations
from typing import Any, Dict, List

from ..searcher import XWikiSearcher
from ..db import XWikiDatabase


class QueryTools:
    def __init__(self, db: XWikiDatabase):
        self._searcher = XWikiSearcher(db)

    def wiki_entities(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        return self._searcher.search_wiki(query, limit=limit)

    def read_pages(self, document_id: str, page_nos: List[int]) -> str:
        return self._searcher.read_pages(document_id, page_nos)

    def get_entity_evidence(self, entity_name: str, limit: int = 3) -> Dict[str, Any]:
        return self._searcher.get_entity_evidence(entity_name, limit=limit)

    def documents(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        return self._searcher.search_documents(query, limit=limit)

    def list_entities(self, domain: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
        return self._searcher.list_entities(domain, limit, offset)


class MaintenanceTools(QueryTools):
    """The same validated read/write boundary for external maintenance agents."""

    def __init__(self, service):
        super().__init__(service.db)
        self._service = service

    def read_entity(self, name: str) -> dict:
        return self._service.read_entity(name)

    def update_entity(self, name: str, content: str, **kwargs) -> dict:
        return self._service.update_entity(name, content, **kwargs)

    def revisions(self, name: str, limit: int = 20) -> list[dict]:
        return self._service.entity_revisions(name, limit)

    def rollback(self, name: str, revision_id: int, **kwargs) -> dict:
        return self._service.rollback_entity(name, revision_id, **kwargs)

    def lint(self) -> dict:
        return self._service.run_structural_lint()

    def sources(self, status: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
        return self._service.list_documents(status, limit, offset)

    def read_page(self, page: str) -> dict:
        return self._service.read_page(page)

    def page_cards(self, domain: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
        return self._service.page_cards(domain, limit, offset)

    def update_page(self, title: str, body: str, **kwargs) -> dict:
        return self._service.update_page(title, body, **kwargs)

    def page_links(self, page_id: str) -> dict:
        return self._service.page_links(page_id)

    def maintenance_tasks(self, limit: int = 50) -> list[dict]:
        return self._service.maintenance_tasks(limit)

    def retry_maintenance_task(self, task_id: int, fingerprint: str) -> dict:
        return self._service.retry_maintenance_task(task_id, fingerprint)
