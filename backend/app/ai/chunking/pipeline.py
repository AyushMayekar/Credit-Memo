from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence


@dataclass(slots=True)
class ChildChunk:
    chunk_id: str
    parent_chunk_id: str
    section_id: str
    section_title: str
    heading_path: list[str]
    page_start: int
    page_end: int
    content_text: str
    embedding_text: str
    token_count: int
    source_record_ids: list[str]
    source_item_ids: list[str]
    quality_classification: str
    search_priority: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParentChunk:
    chunk_id: str
    parent_group_id: str
    parent_part_index: int
    parent_part_count: int
    related_parent_ids: list[str]
    section_id: str
    section_title: str
    heading_level: int | None
    heading_path: list[str]
    page_start: int
    page_end: int
    content_text: str
    embedding_text: str
    token_count: int
    child_chunk_ids: list[str]
    table_chunk_ids: list[str]
    source_record_ids: list[str]
    quality_classification: str
    search_priority: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TableChunk:
    chunk_id: str
    parent_chunk_id: str
    table_id: str
    table_group_id: str
    table_part_index: int
    table_part_count: int
    related_table_chunk_ids: list[str]
    section_id: str
    section_title: str
    heading_path: list[str]
    page_start: int
    page_end: int
    content_text: str
    embedding_text: str
    token_count: int
    quality_classification: str
    search_priority: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChunkingResult:
    parents: list[ParentChunk]
    children: list[ChildChunk]
    tables: list[TableChunk]
    audit: dict[str, Any]


@dataclass(slots=True)
class _ChildDraft:
    temp_id: str
    section_id: str
    section_title: str
    heading_path: list[str]
    page_start: int
    page_end: int
    content_text: str
    token_count: int
    source_record_ids: list[str]
    source_item_ids: list[str]
    quality_classification: str
    search_priority: str
    child_group_id: str
    child_part_index: int
    child_part_count: int
    related_child_ids: list[str]
    warnings: list[str]


@dataclass(slots=True)
class _ParentDraft:
    chunk_id: str
    parent_group_id: str
    parent_part_index: int
    parent_part_count: int
    related_parent_ids: list[str]
    section: dict[str, Any]
    children: list[_ChildDraft]


class HybridTextChunkingPipeline:
    """Create bounded parent contexts and searchable narrative/table children.

    Decisions implemented here:
    - Narrative children: target 350, soft max 500, hard max 600 tokens.
    - Parent contexts: target 1800, soft max 2400, hard max 2700 tokens.
    - Complete narrative children are kept intact inside a parent.
    - Tables are searchable TABLE_DATA children and point to a bounded parent.
    - Large tables split only between complete rows and repeat headers.
    - This module performs no retrieval and no reranking.
    """

    VERSION = "hybrid-structural-chunker-v3.0"

    CHILD_TARGET_TOKENS = 350
    CHILD_SOFT_MAX_TOKENS = 500
    CHILD_HARD_MAX_TOKENS = 600
    CHILD_OVERLAP_TOKENS = 50

    PARENT_TARGET_TOKENS = 1800
    PARENT_SOFT_MAX_TOKENS = 2400
    PARENT_HARD_MAX_TOKENS = 2700

    TABLE_TARGET_TOKENS = 900
    TABLE_SOFT_MAX_TOKENS = 1400
    TABLE_HARD_MAX_TOKENS = 1800

    SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")
    PARAGRAPH_RE = re.compile(r"\n\s*\n+")
    TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)

    def run(
        self,
        parsed_document: Path | str | dict[str, Any],
        *,
        borrower_name: str = "",
        document_name: str | None = None,
        reporting_year: str | None = None,
        document_id: int | None = None,
    ) -> ChunkingResult:
        payload = self._load(parsed_document)
        document = payload.get("document") or {}
        resolved_document_name = (
            document_name
            or document.get("filename")
            or document.get("document_name")
            or "Unknown document"
        )
        sections = payload.get("sections") or []
        records = payload.get("records") or []
        tables = payload.get("tables") or []

        section_map = {str(s.get("section_id")): s for s in sections}
        records_by_section: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            sid = str(record.get("section_id") or "")
            records_by_section.setdefault(sid, []).append(record)
        for items in records_by_section.values():
            items.sort(key=lambda x: (int(x.get("page_start") or 0), str(x.get("record_id") or "")))

        table_by_section: dict[str, list[dict[str, Any]]] = {}
        for table in tables:
            sid = str(table.get("section_id") or "")
            table_by_section.setdefault(sid, []).append(table)
        for items in table_by_section.values():
            items.sort(key=lambda x: (int(x.get("page_number") or 0), str(x.get("table_id") or "")))

        # Build searchable children from parser records without changing the
        # parser's section membership. The parser hierarchy is authoritative.
        child_drafts_by_section: dict[str, list[_ChildDraft]] = {}
        unassigned_records = 0
        for sid, section_records in records_by_section.items():
            section = section_map.get(sid)
            if section is None:
                section = self._fallback_section(sid, section_records)
                section_map[sid] = section
            child_drafts_by_section[sid] = self._children_for_section(
                section, section_records
            )
            if not sid:
                unassigned_records += len(section_records)

        # A parser section belongs to its declared parent_section_id. Records
        # under sibling subsections therefore share the real parsed parent.
        # A top-level section without a parser parent is its own parent anchor.
        parser_parent_ids = {
            str(section.get("parent_section_id"))
            for section in section_map.values()
            if section.get("parent_section_id") is not None
        }
        owner_for_section = {
            sid: self._parent_anchor_id(sid, section_map, parser_parent_ids)
            for sid in section_map
        }

        children_by_parent_section: dict[str, list[_ChildDraft]] = {}
        for sid, drafts in child_drafts_by_section.items():
            owner_id = owner_for_section.get(sid, sid)
            children_by_parent_section.setdefault(owner_id, []).extend(drafts)
        for drafts in children_by_parent_section.values():
            drafts.sort(key=lambda x: (x.page_start, x.page_end, x.temp_id))

        tables_by_parent_section: dict[str, list[dict[str, Any]]] = {}
        for sid, section_tables in table_by_section.items():
            owner_id = owner_for_section.get(sid, sid)
            tables_by_parent_section.setdefault(owner_id, []).extend(section_tables)
        for values in tables_by_parent_section.values():
            values.sort(
                key=lambda x: (
                    int(x.get("page_number") or 0),
                    str(x.get("table_id") or ""),
                )
            )

        parent_drafts: dict[str, list[_ParentDraft]] = {}
        owner_ids = set(children_by_parent_section) | set(tables_by_parent_section)
        for owner_id in sorted(
            owner_ids,
            key=lambda sid: (
                int((section_map.get(sid) or {}).get("page_start") or 0), sid
            ),
        ):
            owner_section = section_map.get(owner_id)
            if owner_section is None:
                owner_section = self._fallback_parent_section(
                    owner_id,
                    children_by_parent_section.get(owner_id, []),
                    tables_by_parent_section.get(owner_id, []),
                )
                section_map[owner_id] = owner_section
            parent_drafts[owner_id] = self._parents_for_section(
                owner_section,
                children_by_parent_section.get(owner_id, []),
            )

        child_to_parent: dict[str, str] = {}
        parents: list[ParentChunk] = []
        for owner_id in self._section_order(section_map, parent_drafts):
            for draft in parent_drafts.get(owner_id, []):
                for child in draft.children:
                    child_to_parent[child.temp_id] = draft.chunk_id
                parents.append(
                    self._final_parent(
                        draft,
                        borrower_name=borrower_name,
                        document_name=resolved_document_name,
                        reporting_year=reporting_year,
                        document_id=document_id,
                    )
                )

        children: list[ChildChunk] = []
        for sid, drafts in child_drafts_by_section.items():
            for draft in drafts:
                parent_id = child_to_parent[draft.temp_id]
                child = self._final_child(
                    draft,
                    parent_id=parent_id,
                    borrower_name=borrower_name,
                    document_name=resolved_document_name,
                    reporting_year=reporting_year,
                    document_id=document_id,
                )
                child.metadata["parser_parent_section_id"] = (
                    section_map.get(sid) or {}
                ).get("parent_section_id")
                child.metadata["parent_anchor_section_id"] = owner_for_section.get(
                    sid, sid
                )
                children.append(child)

        table_chunks: list[TableChunk] = []
        for owner_id in self._section_order(section_map, parent_drafts):
            owner_section = section_map.get(owner_id) or {}
            section_parents = parent_drafts.get(owner_id, [])
            for table in tables_by_parent_section.get(owner_id, []):
                table_section_id = str(table.get("section_id") or owner_id)
                table_section = section_map.get(table_section_id) or owner_section
                parent_id = self._parent_for_table(table, section_parents)
                chunks = self._table_chunks(
                    table,
                    section=table_section,
                    parent_id=parent_id,
                    borrower_name=borrower_name,
                    document_name=resolved_document_name,
                    reporting_year=reporting_year,
                    document_id=document_id,
                )
                for chunk in chunks:
                    chunk.metadata["parser_parent_section_id"] = (
                        table_section.get("parent_section_id")
                    )
                    chunk.metadata["parent_anchor_section_id"] = owner_id
                table_chunks.extend(chunks)

        table_ids_by_parent: dict[str, list[str]] = {}
        for table in table_chunks:
            table_ids_by_parent.setdefault(table.parent_chunk_id, []).append(
                table.chunk_id
            )
        for parent in parents:
            parent.table_chunk_ids[:] = table_ids_by_parent.get(parent.chunk_id, [])
            parent.metadata["table_chunk_ids"] = list(parent.table_chunk_ids)
            parent.metadata["llm_metadata"]["table_chunk_ids"] = list(
                parent.table_chunk_ids
            )

        audit = self._audit(
            payload=payload,
            parents=parents,
            children=children,
            tables=table_chunks,
            unassigned_records=unassigned_records,
        )
        return ChunkingResult(parents, children, table_chunks, audit)

    @staticmethod
    def _parent_anchor_id(
        section_id: str,
        section_map: dict[str, dict[str, Any]],
        parser_parent_ids: set[str],
    ) -> str:
        """Choose an anchor only from the hierarchy emitted by the parser.

        A section that already owns parser child sections remains its own parent
        anchor, so its own narrative is not moved to its grandparent. A leaf
        section belongs to its declared immediate parent. A top-level leaf is
        its own anchor because the parser supplied no higher section.
        """
        if section_id in parser_parent_ids:
            return section_id
        section = section_map.get(section_id) or {}
        declared = section.get("parent_section_id")
        if declared is None or str(declared) not in section_map:
            return section_id
        return str(declared)

    @staticmethod
    def _fallback_parent_section(
        section_id: str,
        children: Sequence[_ChildDraft],
        tables: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        if children:
            first = children[0]
            return {
                "section_id": section_id or "UNASSIGNED",
                "title": first.heading_path[-2] if len(first.heading_path) > 1 else first.section_title,
                "heading_level": None,
                "heading_path": first.heading_path[:-1] or [first.section_title],
                "page_start": min(x.page_start for x in children),
                "page_end": max(x.page_end for x in children),
                "parent_section_id": None,
            }
        return HybridTextChunkingPipeline._fallback_table_section(
            section_id, tables
        )

    def _children_for_section(
        self, section: dict[str, Any], records: Sequence[dict[str, Any]]
    ) -> list[_ChildDraft]:
        drafts: list[_ChildDraft] = []
        section_id = str(section.get("section_id") or "UNASSIGNED")
        for record_index, record in enumerate(records, start=1):
            text = self.clean(record.get("content_text"))
            if not text:
                continue
            group_id = f"CG-{self._safe_id(section_id)}-{record_index:04d}"
            pieces = self._split_narrative(text)
            temp_ids = [f"{group_id}-PART-{i:03d}" for i in range(1, len(pieces) + 1)]
            for index, piece in enumerate(pieces, start=1):
                related = [value for value in temp_ids if value != temp_ids[index - 1]]
                warnings = list(record.get("warnings") or [])
                count = self.count_tokens(piece)
                if count > self.CHILD_HARD_MAX_TOKENS:
                    warnings.append("child_hard_limit_exceeded_by_indivisible_unit")
                drafts.append(
                    _ChildDraft(
                        temp_id=temp_ids[index - 1],
                        section_id=section_id,
                        section_title=str(section.get("title") or record.get("section_title") or "Document"),
                        heading_path=list(section.get("heading_path") or record.get("heading_path") or []),
                        page_start=int(record.get("page_start") or 1),
                        page_end=int(record.get("page_end") or record.get("page_start") or 1),
                        content_text=piece,
                        token_count=count,
                        source_record_ids=[str(record.get("record_id") or "")],
                        source_item_ids=[str(x) for x in record.get("source_item_ids") or []],
                        quality_classification=str(record.get("quality_classification") or "ACCEPTED"),
                        search_priority=self._priority(record.get("quality_classification")),
                        child_group_id=group_id,
                        child_part_index=index,
                        child_part_count=len(pieces),
                        related_child_ids=related,
                        warnings=warnings,
                    )
                )
        return drafts

    def _parents_for_section(
        self, section: dict[str, Any], children: Sequence[_ChildDraft]
    ) -> list[_ParentDraft]:
        section_id = str(section.get("section_id") or "UNASSIGNED")
        group_id = f"PG-{self._safe_id(section_id)}"
        groups: list[list[_ChildDraft]] = []
        current: list[_ChildDraft] = []
        current_tokens = 0

        for child in children:
            proposed = current_tokens + child.token_count
            if not current:
                current = [child]
                current_tokens = child.token_count
                continue
            if proposed <= self.PARENT_TARGET_TOKENS:
                current.append(child)
                current_tokens = proposed
                continue
            if proposed <= self.PARENT_HARD_MAX_TOKENS:
                # Preserve a complete child even above the soft maximum.
                current.append(child)
                current_tokens = proposed
                continue
            groups.append(current)
            current = [child]
            current_tokens = child.token_count
        if current:
            groups.append(current)
        if not groups:
            groups = [[]]

        ids = [f"{group_id}-PART-{i:03d}" for i in range(1, len(groups) + 1)]
        return [
            _ParentDraft(
                chunk_id=ids[i],
                parent_group_id=group_id,
                parent_part_index=i + 1,
                parent_part_count=len(groups),
                related_parent_ids=[value for value in ids if value != ids[i]],
                section=section,
                children=list(group),
            )
            for i, group in enumerate(groups)
        ]

    def _final_child(
        self,
        draft: _ChildDraft,
        *,
        parent_id: str,
        borrower_name: str,
        document_name: str,
        reporting_year: str | None,
        document_id: int | None,
    ) -> ChildChunk:
        embedding = self._narrative_embedding_text(
            draft, borrower_name, document_name, reporting_year
        )
        return ChildChunk(
            chunk_id=draft.temp_id,
            parent_chunk_id=parent_id,
            section_id=draft.section_id,
            section_title=draft.section_title,
            heading_path=draft.heading_path,
            page_start=draft.page_start,
            page_end=draft.page_end,
            content_text=draft.content_text,
            embedding_text=embedding,
            token_count=draft.token_count,
            source_record_ids=draft.source_record_ids,
            source_item_ids=draft.source_item_ids,
            quality_classification=draft.quality_classification,
            search_priority=draft.search_priority,
            metadata={
                "document_id": document_id,
                "document_name": document_name,
                "reporting_year": reporting_year,
                "content_type": "CHILD_CHUNK",
                "parent_chunk_id": parent_id,
                "child_group_id": draft.child_group_id,
                "child_part_index": draft.child_part_index,
                "child_part_count": draft.child_part_count,
                "related_child_ids": draft.related_child_ids,
                "heading_path": draft.heading_path,
                "quality_classification": draft.quality_classification,
                "search_priority": draft.search_priority,
                "warnings": draft.warnings,
                "llm_metadata": {
                    "document_name": document_name,
                    "reporting_year": reporting_year,
                    "content_type": "CHILD_CHUNK",
                    "chunk_id": draft.temp_id,
                    "parent_chunk_id": parent_id,
                    "section_id": draft.section_id,
                    "section_title": draft.section_title,
                    "heading_path": draft.heading_path,
                    "page_start": draft.page_start,
                    "page_end": draft.page_end,
                    "quality_classification": draft.quality_classification,
                    "related_child_ids": draft.related_child_ids,
                },
                "chunk_version": self.VERSION,
            },
        )

    def _final_parent(
        self,
        draft: _ParentDraft,
        *,
        borrower_name: str,
        document_name: str,
        reporting_year: str | None,
        document_id: int | None,
    ) -> ParentChunk:
        section = draft.section
        title = str(section.get("title") or "Document")
        heading_path = list(section.get("heading_path") or [title])
        body_parts: list[str] = []
        active_child_section: str | None = None
        for child in draft.children:
            if child.section_id != active_child_section:
                if child.section_title and child.section_title != title:
                    body_parts.append(child.section_title)
                active_child_section = child.section_id
            body_parts.append(child.content_text)
        body = "\n\n".join(body_parts).strip()
        content = self.clean_parent(title, body)
        pages = [value for child in draft.children for value in (child.page_start, child.page_end)]
        page_start = min(pages, default=int(section.get("page_start") or 1))
        page_end = max(pages, default=int(section.get("page_end") or page_start))
        quality = (
            "REVIEW_REQUIRED"
            if any(c.quality_classification == "REVIEW_REQUIRED" for c in draft.children)
            else "ACCEPTED"
        )
        priority = "LOW" if quality == "REVIEW_REQUIRED" else "NORMAL"
        token_count = self.count_tokens(content)
        warnings: list[str] = []
        if token_count > self.PARENT_HARD_MAX_TOKENS:
            warnings.append("parent_hard_limit_exceeded_by_single_child")
        return ParentChunk(
            chunk_id=draft.chunk_id,
            parent_group_id=draft.parent_group_id,
            parent_part_index=draft.parent_part_index,
            parent_part_count=draft.parent_part_count,
            related_parent_ids=draft.related_parent_ids,
            section_id=str(section.get("section_id") or "UNASSIGNED"),
            section_title=title,
            heading_level=(int(section["heading_level"]) if section.get("heading_level") is not None else None),
            heading_path=heading_path,
            page_start=page_start,
            page_end=page_end,
            content_text=content,
            embedding_text=self._parent_embedding_text(
                title, heading_path, content, borrower_name, document_name, reporting_year
            ),
            token_count=token_count,
            child_chunk_ids=[c.temp_id for c in draft.children],
            table_chunk_ids=[],
            source_record_ids=list(dict.fromkeys(x for c in draft.children for x in c.source_record_ids if x)),
            quality_classification=quality,
            search_priority=priority,
            metadata={
                "document_id": document_id,
                "document_name": document_name,
                "reporting_year": reporting_year,
                "content_type": "PARENT_SECTION",
                "parent_group_id": draft.parent_group_id,
                "parent_part_index": draft.parent_part_index,
                "parent_part_count": draft.parent_part_count,
                "related_parent_ids": draft.related_parent_ids,
                "child_chunk_ids": [c.temp_id for c in draft.children],
                "table_chunk_ids": [],
                "heading_path": heading_path,
                "quality_classification": quality,
                "search_priority": priority,
                "warnings": warnings,
                "llm_metadata": {
                    "document_name": document_name,
                    "reporting_year": reporting_year,
                    "content_type": "PARENT_SECTION",
                    "chunk_id": draft.chunk_id,
                    "section_id": str(section.get("section_id") or "UNASSIGNED"),
                    "section_title": title,
                    "heading_path": heading_path,
                    "page_start": page_start,
                    "page_end": page_end,
                    "parent_group_id": draft.parent_group_id,
                    "parent_part_index": draft.parent_part_index,
                    "parent_part_count": draft.parent_part_count,
                    "related_parent_ids": draft.related_parent_ids,
                    "quality_classification": quality,
                    "table_chunk_ids": [],
                },
                "chunk_version": self.VERSION,
            },
        )

    def _table_chunks(
        self,
        table: dict[str, Any],
        *,
        section: dict[str, Any],
        parent_id: str,
        borrower_name: str,
        document_name: str,
        reporting_year: str | None,
        document_id: int | None,
    ) -> list[TableChunk]:
        table_id = str(table.get("table_id") or self._stable_table_id(table))
        group_id = f"TG-{self._safe_id(table_id)}"
        rows = self._table_rows(table)
        header_rows, body_rows = self._header_and_body_rows(table, rows)
        parts = self._split_table_rows(header_rows, body_rows)
        ids = [f"{group_id}-PART-{i:03d}" for i in range(1, len(parts) + 1)]
        page = int(table.get("page_number") or section.get("page_start") or 1)
        title = str(table.get("title") or table.get("section_title") or section.get("title") or "Table")
        heading_path = list(table.get("heading_path") or section.get("heading_path") or [title])
        quality = str(table.get("quality_classification") or "REVIEW_REQUIRED")
        priority = "HIGH" if quality == "ACCEPTED" else "NORMAL"
        output: list[TableChunk] = []
        for i, part_rows in enumerate(parts):
            markdown = self._rows_to_markdown(part_rows)
            introduction = self._table_intro(table, title)
            content = f"{introduction}\n\n{markdown}".strip()
            count = self.count_tokens(content)
            warnings = list(table.get("review_reasons") or table.get("warnings") or [])
            if count > self.TABLE_HARD_MAX_TOKENS:
                warnings.append("table_hard_limit_exceeded_by_single_row")
            output.append(
                TableChunk(
                    chunk_id=ids[i],
                    parent_chunk_id=parent_id,
                    table_id=table_id,
                    table_group_id=group_id,
                    table_part_index=i + 1,
                    table_part_count=len(parts),
                    related_table_chunk_ids=[value for value in ids if value != ids[i]],
                    section_id=str(table.get("section_id") or section.get("section_id") or "UNASSIGNED"),
                    section_title=str(table.get("section_title") or section.get("title") or "Document"),
                    heading_path=heading_path,
                    page_start=page,
                    page_end=page,
                    content_text=content,
                    embedding_text=self._table_embedding_text(
                        content, heading_path, borrower_name, document_name, reporting_year
                    ),
                    token_count=count,
                    quality_classification=quality,
                    search_priority=priority,
                    metadata={
                        "document_id": document_id,
                        "document_name": document_name,
                        "reporting_year": reporting_year,
                        "content_type": "TABLE_DATA",
                        "parent_chunk_id": parent_id,
                        "table_id": table_id,
                        "table_group_id": group_id,
                        "table_part_index": i + 1,
                        "table_part_count": len(parts),
                        "related_table_chunk_ids": [value for value in ids if value != ids[i]],
                        "detected_periods": table.get("detected_periods") or [],
                        "detected_units": table.get("detected_units") or [],
                        "source_item_ids": table.get("source_item_ids") or [],
                        "source_bbox": table.get("source_bbox"),
                        "quality_classification": quality,
                        "search_priority": priority,
                        "warnings": warnings,
                        "llm_metadata": {
                            "document_name": document_name,
                            "reporting_year": reporting_year,
                            "content_type": "TABLE_DATA",
                            "chunk_id": ids[i],
                            "parent_chunk_id": parent_id,
                            "table_id": table_id,
                            "table_part_index": i + 1,
                            "table_part_count": len(parts),
                            "section_id": str(table.get("section_id") or section.get("section_id") or "UNASSIGNED"),
                            "section_title": str(table.get("section_title") or section.get("title") or "Document"),
                            "heading_path": heading_path,
                            "page_start": page,
                            "page_end": page,
                            "detected_periods": table.get("detected_periods") or [],
                            "detected_units": table.get("detected_units") or [],
                            "quality_classification": quality,
                            "related_table_chunk_ids": [value for value in ids if value != ids[i]],
                        },
                        "chunk_version": self.VERSION,
                    },
                )
            )
        return output

    def _parent_for_table(
        self, table: dict[str, Any], parents: Sequence[_ParentDraft]
    ) -> str:
        if not parents:
            raise ValueError(f"No parent was created for table {table.get('table_id')}")
        page = int(table.get("page_number") or 1)
        with_page: list[tuple[int, _ParentDraft]] = []
        for parent in parents:
            pages = [x for c in parent.children for x in (c.page_start, c.page_end)]
            start = min(pages, default=int(parent.section.get("page_start") or 1))
            end = max(pages, default=int(parent.section.get("page_end") or start))
            if start <= page <= end:
                return parent.chunk_id
            with_page.append((min(abs(page - start), abs(page - end)), parent))
        return min(with_page, key=lambda x: x[0])[1].chunk_id

    def _split_narrative(self, text: str) -> list[str]:
        if self.count_tokens(text) <= self.CHILD_SOFT_MAX_TOKENS:
            return [text]
        units = self._semantic_units(text)
        parts: list[str] = []
        current: list[str] = []
        current_tokens = 0
        for unit in units:
            unit_tokens = self.count_tokens(unit)
            if unit_tokens > self.CHILD_HARD_MAX_TOKENS:
                for forced in self._hard_split(unit, self.CHILD_TARGET_TOKENS, self.CHILD_OVERLAP_TOKENS):
                    if current:
                        parts.append(" ".join(current).strip())
                        current, current_tokens = [], 0
                    parts.append(forced)
                continue
            proposed = current_tokens + unit_tokens
            if not current or proposed <= self.CHILD_TARGET_TOKENS:
                current.append(unit)
                current_tokens = proposed
            elif proposed <= self.CHILD_HARD_MAX_TOKENS:
                current.append(unit)
                current_tokens = proposed
            else:
                parts.append(" ".join(current).strip())
                current = [unit]
                current_tokens = unit_tokens
        if current:
            parts.append(" ".join(current).strip())
        return [x for x in parts if x]

    def _semantic_units(self, text: str) -> list[str]:
        paragraphs = [self.clean(x) for x in self.PARAGRAPH_RE.split(text) if self.clean(x)]
        if len(paragraphs) > 1:
            units: list[str] = []
            for paragraph in paragraphs:
                if self.count_tokens(paragraph) <= self.CHILD_SOFT_MAX_TOKENS:
                    units.append(paragraph)
                else:
                    units.extend(self._sentences(paragraph))
            return units
        return self._sentences(text)

    def _sentences(self, text: str) -> list[str]:
        values = [self.clean(x) for x in self.SENTENCE_RE.split(text) if self.clean(x)]
        return values or [self.clean(text)]

    def _hard_split(self, text: str, target: int, overlap: int) -> list[str]:
        words = text.split()
        if not words:
            return []
        output: list[str] = []
        start = 0
        while start < len(words):
            end = min(len(words), start + target)
            part = " ".join(words[start:end]).strip()
            if part:
                output.append(part)
            if end >= len(words):
                break
            start = max(start + 1, end - overlap)
        return output

    def _split_table_rows(
        self, header_rows: list[list[Any]], body_rows: list[list[Any]]
    ) -> list[list[list[Any]]]:
        if not body_rows:
            return [header_rows]
        parts: list[list[list[Any]]] = []
        current: list[list[Any]] = list(header_rows)
        current_tokens = self.count_tokens(self._rows_to_markdown(current))
        for row in body_rows:
            row_tokens = self.count_tokens(self._rows_to_markdown([row]))
            proposed = current_tokens + row_tokens
            has_body = len(current) > len(header_rows)
            if not has_body or proposed <= self.TABLE_TARGET_TOKENS:
                current.append(row)
                current_tokens = proposed
            elif proposed <= self.TABLE_HARD_MAX_TOKENS:
                current.append(row)
                current_tokens = proposed
            else:
                parts.append(current)
                current = list(header_rows) + [row]
                current_tokens = self.count_tokens(self._rows_to_markdown(current))
        if current:
            parts.append(current)
        return parts

    def _table_rows(self, table: dict[str, Any]) -> list[list[Any]]:
        rows = table.get("normalized_rows")
        if isinstance(rows, list) and rows:
            return [list(row) for row in rows if isinstance(row, list)]
        header_rows = table.get("header_rows") or []
        body_rows = table.get("body_rows") or []
        output = [[row.get("label", "")] + list(row.get("cells") or []) for row in header_rows]
        output.extend([[row.get("label", "")] + list(row.get("cells") or []) for row in body_rows])
        if output:
            return output
        markdown = str(table.get("markdown") or "").strip()
        return self._markdown_rows(markdown)

    def _header_and_body_rows(
        self, table: dict[str, Any], rows: list[list[Any]]
    ) -> tuple[list[list[Any]], list[list[Any]]]:
        header_count = len(table.get("header_rows") or [])
        if header_count <= 0:
            header_count = 1 if rows else 0
        return rows[:header_count], rows[header_count:]

    def _rows_to_markdown(self, rows: Sequence[Sequence[Any]]) -> str:
        rows = [list(row) for row in rows]
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        padded = [row + [""] * (width - len(row)) for row in rows]
        def render(row: Sequence[Any]) -> str:
            return "| " + " | ".join(self._escape_cell(x) for x in row) + " |"
        return "\n".join([render(padded[0]), render(["---"] * width), *[render(x) for x in padded[1:]]])

    def _table_intro(self, table: dict[str, Any], title: str) -> str:
        periods = ", ".join(str(x) for x in table.get("detected_periods") or [])
        units = ", ".join(str(x) for x in table.get("detected_units") or [])
        parts = [f"Table: {title}."]
        if periods:
            parts.append(f"Periods: {periods}.")
        if units:
            parts.append(f"Units: {units}.")
        return " ".join(parts)

    def _narrative_embedding_text(self, draft: _ChildDraft, borrower: str, document: str, year: str | None) -> str:
        return self._context_prefix(borrower, document, year, draft.heading_path, draft.page_start, draft.page_end) + "\n" + draft.content_text

    def _parent_embedding_text(self, title: str, path: list[str], content: str, borrower: str, document: str, year: str | None) -> str:
        return self._context_prefix(borrower, document, year, path, 0, 0) + f"\nParent section: {title}\n{content}"

    def _table_embedding_text(self, content: str, path: list[str], borrower: str, document: str, year: str | None) -> str:
        return self._context_prefix(borrower, document, year, path, 0, 0) + "\nContent type: financial table\n" + content

    @staticmethod
    def _context_prefix(borrower: str, document: str, year: str | None, path: list[str], page_start: int, page_end: int) -> str:
        values = []
        if borrower:
            values.append(f"Borrower: {borrower}")
        values.append(f"Document: {document}")
        if year:
            values.append(f"Reporting period: {year}")
        if path:
            values.append("Section: " + " > ".join(str(x) for x in path))
        if page_start:
            values.append(f"Pages: {page_start}" if page_start == page_end else f"Pages: {page_start}-{page_end}")
        return "\n".join(values)

    def _audit(self, *, payload: dict[str, Any], parents: list[ParentChunk], children: list[ChildChunk], tables: list[TableChunk], unassigned_records: int) -> dict[str, Any]:
        parsed_records = payload.get("records") or []
        expected_record_ids = {str(x.get("record_id")) for x in parsed_records if x.get("content_text")}
        represented_record_ids = {x for child in children for x in child.source_record_ids if x}
        expected_table_ids = {str(x.get("table_id")) for x in payload.get("tables") or []}
        represented_table_ids = {table.table_id for table in tables}
        parent_ids = {p.chunk_id for p in parents}
        hard_child = [x.chunk_id for x in children if x.token_count > self.CHILD_HARD_MAX_TOKENS]
        hard_parent = [x.chunk_id for x in parents if x.token_count > self.PARENT_HARD_MAX_TOKENS]
        hard_table = [x.chunk_id for x in tables if x.token_count > self.TABLE_HARD_MAX_TOKENS]
        broken_links = [x.chunk_id for x in [*children, *tables] if x.parent_chunk_id not in parent_ids]
        duplicate_ids = self._duplicates([x.chunk_id for x in [*parents, *children, *tables]])
        return {
            "chunker_version": self.VERSION,
            "parsed_record_count": len(parsed_records),
            "represented_record_count": len(represented_record_ids),
            "missing_record_ids": sorted(expected_record_ids - represented_record_ids),
            "parsed_table_count": len(expected_table_ids),
            "represented_table_count": len(represented_table_ids),
            "missing_table_ids": sorted(expected_table_ids - represented_table_ids),
            "parent_count": len(parents),
            "child_count": len(children),
            "table_chunk_count": len(tables),
            "unassigned_record_count": unassigned_records,
            "children_over_hard_limit": hard_child,
            "parents_over_hard_limit": hard_parent,
            "tables_over_hard_limit": hard_table,
            "broken_parent_links": broken_links,
            "duplicate_chunk_ids": duplicate_ids,
            "min_child_tokens": min((x.token_count for x in children), default=0),
            "max_child_tokens": max((x.token_count for x in children), default=0),
            "min_parent_tokens": min((x.token_count for x in parents), default=0),
            "max_parent_tokens": max((x.token_count for x in parents), default=0),
            "max_table_tokens": max((x.token_count for x in tables), default=0),
            "status": "PASS" if not any([expected_record_ids - represented_record_ids, expected_table_ids - represented_table_ids, hard_child, hard_parent, hard_table, broken_links, duplicate_ids]) else "REVIEW_REQUIRED",
        }

    @classmethod
    def count_tokens(cls, text: str) -> int:
        # Stable local estimate. No tokenizer download and no model dependency.
        return len(cls.TOKEN_RE.findall(text or ""))

    @staticmethod
    def clean(value: Any) -> str:
        text = str(value or "").replace("\u00ad", "").replace("\u00a0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        return text.strip()

    @staticmethod
    def clean_parent(title: str, body: str) -> str:
        return f"{title}\n\n{body}".strip() if body else title.strip()

    @staticmethod
    def _priority(quality: Any) -> str:
        return "LOW" if str(quality or "").upper() == "REVIEW_REQUIRED" else "NORMAL"

    @staticmethod
    def _load(value: Path | str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return json.loads(Path(value).read_text(encoding="utf-8"))

    @staticmethod
    def _fallback_section(sid: str, records: Sequence[dict[str, Any]]) -> dict[str, Any]:
        first = records[0] if records else {}
        title = str(first.get("section_title") or "Document")
        return {
            "section_id": sid or "UNASSIGNED",
            "title": title,
            "heading_level": None,
            "heading_path": list(first.get("heading_path") or [title]),
            "page_start": int(first.get("page_start") or 1),
            "page_end": int(first.get("page_end") or first.get("page_start") or 1),
        }

    @staticmethod
    def _fallback_table_section(sid: str, tables: Sequence[dict[str, Any]]) -> dict[str, Any]:
        first = tables[0] if tables else {}
        title = str(first.get("section_title") or "Document tables")
        page = int(first.get("page_number") or 1)
        return {"section_id": sid or "UNASSIGNED", "title": title, "heading_level": None, "heading_path": list(first.get("heading_path") or [title]), "page_start": page, "page_end": page}

    @staticmethod
    def _section_order(section_map: dict[str, dict[str, Any]], parents: dict[str, list[_ParentDraft]]) -> list[str]:
        return sorted(parents, key=lambda sid: (int(section_map.get(sid, {}).get("page_start") or 0), sid))

    @staticmethod
    def _safe_id(value: str) -> str:
        output = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
        return output[:80] or "UNASSIGNED"

    @staticmethod
    def _stable_table_id(table: dict[str, Any]) -> str:
        raw = json.dumps(table, sort_keys=True, default=str).encode("utf-8")
        return "TABLE-" + hashlib.sha1(raw).hexdigest()[:12].upper()

    @staticmethod
    def _escape_cell(value: Any) -> str:
        return str(value or "").replace("|", "\\|").replace("\n", " ")

    @staticmethod
    def _duplicates(values: Sequence[str]) -> list[str]:
        seen: set[str] = set()
        duplicate: set[str] = set()
        for value in values:
            if value in seen:
                duplicate.add(value)
            seen.add(value)
        return sorted(duplicate)

    @staticmethod
    def _markdown_rows(markdown: str) -> list[list[str]]:
        output: list[list[str]] = []
        for line in markdown.splitlines():
            line = line.strip()
            if not (line.startswith("|") and line.endswith("|")):
                continue
            cells = [x.strip() for x in line[1:-1].split("|")]
            if cells and all(re.fullmatch(r":?-{3,}:?", x or "") for x in cells):
                continue
            output.append(cells)
        return output


def run(
    parsed_path: Path | str,
    *,
    borrower_name: str = "",
    document_name: str | None = None,
    reporting_year: str | None = None,
    document_id: int | None = None,
) -> dict[str, Any]:
    result = HybridTextChunkingPipeline().run(
        parsed_path,
        borrower_name=borrower_name,
        document_name=document_name,
        reporting_year=reporting_year,
        document_id=document_id,
    )
    return {
        "parents": [asdict(x) for x in result.parents],
        "children": [asdict(x) for x in result.children],
        "tables": [asdict(x) for x in result.tables],
        "audit": result.audit,
    }
