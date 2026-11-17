from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ParentChunk:
    chunk_id: str
    source_section_id: str
    section_title: str
    page_start: int
    page_end: int
    content_text: str
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChildChunk:
    chunk_id: str
    parent_chunk_id: str
    parent_source_section_id: str
    section_title: str
    page_start: int
    page_end: int
    chunk_index: int
    content_text: str
    embedding_text: str
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TableChunk:
    chunk_id: str
    table_id: str
    section_title: str | None
    page_number: int
    content_text: str
    embedding_text: str
    token_count: int
    quality_classification: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TextChunkingResult:
    parents: list[ParentChunk]
    children: list[ChildChunk]
    tables: list[TableChunk]
