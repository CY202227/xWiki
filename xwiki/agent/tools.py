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
