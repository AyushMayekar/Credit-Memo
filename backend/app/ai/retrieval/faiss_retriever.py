from __future__ import annotations

from dataclasses import dataclass
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
    """A retrieved child/table citation plus bounded parent context for the LLM."""

    source_id: str
    score: float
    raw_score: float
    vector_id: int
    content_id: int
    parent_content_id: int | None
    content_type: str
    text: str
    context_text: str
    section_title: str | None
    page_number: int | None
    page_end: int | None
    source_reference: str | None
    table_image_path: str | None
    visual_image_path: str | None
    metadata: dict[str, Any]


class ApplicationFaissRetriever:
    """Retrieve child/table vectors, then expand to at most N distinct parents."""

    PRIORITY_MULTIPLIER = {
        "HIGH": 1.05,
        "NORMAL": 1.00,
        "LOW": 0.75,
    }

    def __init__(self, session: Session, index_path: Path) -> None:
        self.session = session
        self.index_path = index_path

    def search(
        self,
        *,
        query_vector: list[float],
        application_id: int,
        top_k: int = 2,
        candidate_k: int = 24,
    ) -> list[RetrievedEvidence]:
        """
        Search child/table vectors and return at most `top_k` distinct contexts.

        CHILD_CHUNK vectors retrieve their PARENT_SECTION as LLM context.
        TABLE_DATA vectors use their normalized table text as their own context.
        """
        if top_k < 1:
            return []
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

        # Candidate expansion does not affect LLM context size. It only improves
        # the chance of finding two relevant, distinct parents in a shared index.
        search_k = min(
            int(index.ntotal),
            max(candidate_k, top_k * 8, application_vector_count),
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

        candidates: list[tuple[float, float, FaissVectorMapping, DocumentContent]] = []
        for vector_id, raw_score in ranked_ids:
            mapping = mapping_by_vector.get(vector_id)
            if mapping is None:
                continue
            content = self.session.get(DocumentContent, mapping.content_id)
            if content is None or not (content.content_text or "").strip():
                continue
            priority = str(
                (content.content_metadata or {}).get("search_priority", "NORMAL")
            ).upper()
            adjusted_score = raw_score * self.PRIORITY_MULTIPLIER.get(priority, 1.0)
            candidates.append((adjusted_score, raw_score, mapping, content))

        candidates.sort(key=lambda item: item[0], reverse=True)
        selected: list[RetrievedEvidence] = []
        seen_contexts: set[tuple[str, int]] = set()
        seen_texts: set[str] = set()

        for adjusted_score, raw_score, mapping, content in candidates:
            if content.content_type == "CHILD_CHUNK" and content.parent_content_id:
                parent = self.session.get(DocumentContent, content.parent_content_id)
                if parent is None or parent.content_type != "PARENT_SECTION":
                    continue
                context_key = ("PARENT_SECTION", parent.id)
                context_text = (parent.content_text or "").strip()
            else:
                parent = None
                context_key = (content.content_type, content.id)
                context_text = (content.content_text or "").strip()

            if context_key in seen_contexts or not context_text:
                continue
            normalized_context = " ".join(context_text.split()).casefold()
            if normalized_context in seen_texts:
                continue

            table = self.session.scalar(
                select(ExtractedTable).where(ExtractedTable.content_id == content.id)
            )
            image = self.session.scalar(
                select(ExtractedImage).where(ExtractedImage.content_id == content.id)
            )
            source_number = len(selected) + 1
            selected.append(
                RetrievedEvidence(
                    source_id=f"SRC-{source_number}",
                    score=round(adjusted_score, 6),
                    raw_score=round(raw_score, 6),
                    vector_id=int(mapping.faiss_vector_id),
                    content_id=content.id,
                    parent_content_id=content.parent_content_id,
                    content_type=content.content_type,
                    text=content.content_text,
                    context_text=context_text,
                    section_title=content.section_title,
                    page_number=content.page_number,
                    page_end=content.page_end,
                    source_reference=content.source_reference,
                    table_image_path=getattr(table, "image_path", None),
                    visual_image_path=getattr(image, "image_path", None),
                    metadata={
                        **(content.content_metadata or {}),
                        "retrieved_child_content_id": content.id,
                        "expanded_parent_content_id": getattr(parent, "id", None),
                    },
                )
            )
            seen_contexts.add(context_key)
            seen_texts.add(normalized_context)
            if len(selected) >= top_k:
                break

        return selected
