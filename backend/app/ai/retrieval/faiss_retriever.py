from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    DocumentContent,
    ExtractedImage,
    ExtractedTable,
    FaissVectorMapping,
)


@dataclass(frozen=True, slots=True)
class RetrievedEvidence:
    """A parent or table citation returned by the retrieval layer.

    The LLM receives only PARENT_SECTION and TABLE_DATA evidence. Narrative
    child chunks are used to find parents and are never sent to the LLM.
    """

    source_id: str
    score: float
    raw_score: float
    vector_id: int
    content_id: int
    parent_content_id: int | None
    content_type: str
    text: str
    section_title: str | None
    page_number: int | None
    page_end: int | None
    source_reference: str | None
    table_image_path: str | None
    visual_image_path: str | None
    metadata: dict[str, Any]
    chunk_id: str | None = None
    related_parents: list[dict[str, Any]] = field(default_factory=list)


class ApplicationFaissRetriever:
    """Search child/table vectors and return parents plus matched tables.

    Fixed rules:
    - Inspect the top eight usable child results.
    - Select at most two distinct parents, and at least one when evidence exists.
    - Use FAISS similarity only. No priority multiplier and no reranking.
    - A table match returns the stored table chunk as-is and its bounded parent.
    """

    INSPECT_LIMIT = 8
    DEFAULT_CANDIDATE_K = 24
    MAX_PARENTS = 2

    def __init__(self, session: Session, index_path: Path) -> None:
        self.session = session
        self.index_path = index_path
        self._chunk_map_cache: dict[tuple[int, int], dict[str, DocumentContent]] = {}

    def search(
        self,
        *,
        query_vector: list[float],
        application_id: int,
        top_k: int = 2,
        candidate_k: int = DEFAULT_CANDIDATE_K,
    ) -> list[RetrievedEvidence]:
        """Search vectors and return at most `top_k` distinct parent contexts."""
        max_parents = max(1, min(int(top_k), self.MAX_PARENTS))
        if not self.index_path.exists():
            raise FileNotFoundError(f"FAISS index not found: {self.index_path}")

        index = faiss.read_index(str(self.index_path))
        vector = np.asarray([query_vector], dtype="float32")
        if vector.ndim != 2 or vector.shape[1] != index.d:
            raise ValueError(
                f"Query dimension {vector.shape[1]} != FAISS dimension {index.d}"
            )
        if not np.isfinite(vector).all():
            raise ValueError("Query embedding contains non-finite values")
        faiss.normalize_L2(vector)

        application_vector_count = int(
            self.session.scalar(
                select(func.count(FaissVectorMapping.id)).where(
                    FaissVectorMapping.application_id == application_id,
                    FaissVectorMapping.is_active.is_(True),
                )
            )
            or 0
        )
        if application_vector_count == 0:
            return []

        # Faiss is searched widely enough to find this application's vectors in a
        # shared index. Only the first eight usable results are inspected for
        # parent/table selection; extra candidates never reach the LLM.
        search_k = min(
            int(index.ntotal),
            max(
                int(candidate_k),
                self.INSPECT_LIMIT * 4,
                application_vector_count,
            ),
        )
        scores, ids = index.search(vector, search_k)
        ranked_ids = [
            (int(vector_id), float(score))
            for vector_id, score in zip(ids[0], scores[0])
            if int(vector_id) >= 0
        ]
        if not ranked_ids:
            return []

        mappings = list(
            self.session.scalars(
                select(FaissVectorMapping).where(
                    FaissVectorMapping.faiss_vector_id.in_(
                        [vector_id for vector_id, _ in ranked_ids]
                    ),
                    FaissVectorMapping.application_id == application_id,
                    FaissVectorMapping.is_active.is_(True),
                )
            )
        )
        mapping_by_vector = {
            int(mapping.faiss_vector_id): mapping for mapping in mappings
        }

        # Group usable results by parent. Parent order follows first appearance
        # in the similarity-ranked top eight, so no reranking is applied.
        groups: dict[int, dict[str, Any]] = {}
        parent_order: list[int] = []
        seen_table_content_ids: set[int] = set()
        inspected = 0

        for vector_id, raw_score in ranked_ids:
            if inspected >= self.INSPECT_LIMIT:
                break

            mapping = mapping_by_vector.get(vector_id)
            if mapping is None:
                continue
            content = self.session.get(DocumentContent, mapping.content_id)
            if content is None or not (content.content_text or "").strip():
                continue
            if content.content_type not in {"CHILD_CHUNK", "TABLE_DATA"}:
                continue
            if content.parent_content_id is None:
                continue

            parent = self.session.get(DocumentContent, content.parent_content_id)
            if parent is None or parent.content_type != "PARENT_SECTION":
                continue

            inspected += 1

            if parent.id not in groups:
                if len(groups) >= max_parents:
                    continue
                groups[parent.id] = {
                    "parent": parent,
                    "score": raw_score,
                    "raw_score": raw_score,
                    "vector_id": vector_id,
                    "tables": [],
                }
                parent_order.append(parent.id)

            if content.content_type == "TABLE_DATA":
                if content.id in seen_table_content_ids:
                    continue
                seen_table_content_ids.add(content.id)
                groups[parent.id]["tables"].append(
                    (raw_score, vector_id, content)
                )

        selected: list[RetrievedEvidence] = []
        for parent_id in parent_order:
            group = groups[parent_id]
            parent = group["parent"]
            chunk_map = self.parent_chunk_map(
                application_id, parent.document_id
            )
            selected.append(
                self.parent_evidence(
                    parent,
                    application_id=application_id,
                    chunk_map=chunk_map,
                    score=group["score"],
                    raw_score=group["raw_score"],
                    vector_id=group["vector_id"],
                )
            )
            for raw_score, vector_id, table in group["tables"]:
                selected.append(
                    self.table_evidence(
                        table,
                        parent,
                        application_id=application_id,
                        chunk_map=chunk_map,
                        score=raw_score,
                        raw_score=raw_score,
                        vector_id=vector_id,
                    )
                )

        return selected

    def parent_evidence(
        self,
        parent: DocumentContent,
        *,
        application_id: int,
        chunk_map: dict[str, DocumentContent] | None = None,
        score: float = 0.0,
        raw_score: float = 0.0,
        vector_id: int = -1,
    ) -> RetrievedEvidence:
        """Build a parent evidence item for the LLM."""
        if chunk_map is None:
            chunk_map = self.parent_chunk_map(
                application_id, parent.document_id
            )
        return RetrievedEvidence(
            source_id=self.stable_source_id(parent),
            score=round(float(score), 6),
            raw_score=round(float(raw_score), 6),
            vector_id=int(vector_id),
            content_id=parent.id,
            parent_content_id=parent.id,
            content_type="PARENT_SECTION",
            text=parent.content_text or "",
            section_title=parent.section_title,
            page_number=parent.page_number,
            page_end=parent.page_end,
            source_reference=parent.source_reference,
            table_image_path=None,
            visual_image_path=None,
            metadata={
                **(parent.content_metadata or {}),
                "chunk_id": self.chunk_id(parent),
                "parent_chunk_id": self.chunk_id(parent),
                "document_id": parent.document_id,
            },
            chunk_id=self.chunk_id(parent),
            related_parents=self.related_parent_previews(parent, chunk_map),
        )

    def table_evidence(
        self,
        table: DocumentContent,
        parent: DocumentContent,
        *,
        application_id: int,
        chunk_map: dict[str, DocumentContent] | None = None,
        score: float = 0.0,
        raw_score: float = 0.0,
        vector_id: int = -1,
    ) -> RetrievedEvidence:
        """Build a table evidence item. The table text is returned exactly as stored."""
        if chunk_map is None:
            chunk_map = self.parent_chunk_map(
                application_id, parent.document_id
            )
        extracted = self.session.scalar(
            select(ExtractedTable).where(ExtractedTable.content_id == table.id)
        )
        image = self.session.scalar(
            select(ExtractedImage).where(ExtractedImage.content_id == table.id)
        )
        return RetrievedEvidence(
            source_id=self.stable_source_id(table),
            score=round(float(score), 6),
            raw_score=round(float(raw_score), 6),
            vector_id=int(vector_id),
            content_id=table.id,
            parent_content_id=parent.id,
            content_type="TABLE_DATA",
            text=table.content_text or "",
            section_title=table.section_title,
            page_number=table.page_number,
            page_end=table.page_end,
            source_reference=table.source_reference,
            table_image_path=getattr(extracted, "image_path", None),
            visual_image_path=getattr(image, "image_path", None),
            metadata={
                **(table.content_metadata or {}),
                "chunk_id": self.chunk_id(table),
                "parent_chunk_id": self.chunk_id(parent),
                "document_id": table.document_id,
            },
            chunk_id=self.chunk_id(table),
            related_parents=self.related_parent_previews(parent, chunk_map),
        )

    def parent_chunk_map(
        self, application_id: int, document_id: int | None = None
    ) -> dict[str, DocumentContent]:
        """Map chunker parent IDs to PostgreSQL rows for related-parent lookup."""
        key = (int(application_id), int(document_id or 0))
        cached = self._chunk_map_cache.get(key)
        if cached is not None:
            return cached

        query = select(DocumentContent).where(
            DocumentContent.application_id == application_id,
            DocumentContent.content_type == "PARENT_SECTION",
        )
        if document_id is not None:
            query = query.where(DocumentContent.document_id == document_id)
        parents = list(self.session.scalars(query))
        result = {
            chunk_id: parent
            for parent in parents
            if (chunk_id := self.chunk_id(parent))
        }
        self._chunk_map_cache[key] = result
        return result

    def fetch_parents_by_chunk_ids(
        self,
        *,
        application_id: int,
        document_id: int,
        chunk_ids: list[str],
    ) -> list[DocumentContent]:
        """Fetch parent rows by chunker IDs, preserving request order."""
        chunk_map = self.parent_chunk_map(application_id, document_id)
        output: list[DocumentContent] = []
        seen: set[int] = set()
        for chunk_id in chunk_ids:
            parent = chunk_map.get(chunk_id)
            if parent is None or parent.id in seen:
                continue
            seen.add(parent.id)
            output.append(parent)
        return output

    def related_parent_previews(
        self,
        parent: DocumentContent,
        chunk_map: dict[str, DocumentContent],
    ) -> list[dict[str, Any]]:
        metadata = parent.content_metadata or {}
        related_ids = metadata.get("related_parent_ids") or []
        output: list[dict[str, Any]] = []
        for chunk_id in related_ids:
            related = chunk_map.get(str(chunk_id))
            if related is None:
                continue
            related_metadata = related.content_metadata or {}
            output.append(
                {
                    "parent_id": str(chunk_id),
                    "content_id": related.id,
                    "document_id": related.document_id,
                    "section_title": related.section_title,
                    "pages": self.pages(related),
                    "part": self.part_label(related_metadata),
                }
            )
        return output

    @staticmethod
    def stable_source_id(content: DocumentContent) -> str:
        return f"DOC{content.document_id}-CONTENT-{content.id}"

    @staticmethod
    def chunk_id(content: DocumentContent) -> str | None:
        metadata = content.content_metadata or {}
        return metadata.get("chunk_id") or (
            metadata.get("llm_metadata") or {}
        ).get("chunk_id")

    @staticmethod
    def pages(content: DocumentContent) -> str:
        start = content.page_number
        end = content.page_end or content.page_number
        if start is None:
            return ""
        return str(start) if start == end else f"{start}-{end}"

    @staticmethod
    def part_label(metadata: dict[str, Any]) -> str | None:
        index = metadata.get("parent_part_index")
        count = metadata.get("parent_part_count")
        if index and count:
            return f"{index} of {count}"
        return None
