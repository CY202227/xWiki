"""Public and persistence-facing models for the xWiki service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PageSummaryLLM(BaseModel):
  page_summary: str
  last_active_key: str = ""


class MetaEntryLLM(BaseModel):
  doc_date: str = Field(description="YYYY-MM-DD or unknown")
  canonical_title: str = Field(description="标准化标题")
  summary: str = Field(description="文档摘要")
  topic_tags: List[str] = Field(default_factory=list)
  doc_type: str = Field(default="未分类", description="领域分类")


class OutlineLLM(BaseModel):
  items: List[Dict[str, Any]] = Field(default_factory=list)


class EntityListLLM(BaseModel):
  entities: List[Dict[str, str]] = Field(default_factory=list)


class ConsensusLLM(BaseModel):
  new_consensus: str = Field(description="对实体的新增或修订定义")
  key_attributes: Dict[str, str] = Field(default_factory=dict)


@dataclass(frozen=True)
class ParsedPage:
  page_no: int
  content: str


@dataclass(frozen=True)
class IngestedDocument:
  document_id: str
  title: str
  source_path: str
  raw_path: str
  status: str
  canonical_title: str
  doc_type: str
  total_pages: int


@dataclass(frozen=True)
class SearchResult:
  kind: str
  source_id: str
  title: str
  score: float
  snippet: str
  payload: Dict[str, Any]
