from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.ai.embedding_model import get_embedding_client
from app.ai.prompts.retrieval_prompts import retrieval_query
from app.ai.retrieval.faiss_retriever import (
    ApplicationFaissRetriever,
    RetrievedEvidence,
)


@dataclass(frozen=True, slots=True)
class RetrievalRequest:
    application_id: int
    application_reference: str
    borrower_name: str


class MemoBatchRetriever:
    """Retrieve parents and matched tables for one memo batch.

    The LLM receives only PARENT and TABLE evidence. Narrative children are
    used to find parents and are never placed in the packet. Tables are kept
    exactly as stored; nothing is trimmed.
    """

    def __init__(self, retriever: ApplicationFaissRetriever) -> None:
        self.retriever = retriever
        self.embedder = get_embedding_client()

    def retrieve(
        self,
        *,
        request: RetrievalRequest,
        batch,
    ) -> tuple[list[RetrievedEvidence], list[dict[str, Any]]]:
        return self.search(request=request, query=batch.query, batch=batch)

    def search(
        self,
        *,
        request: RetrievalRequest,
        query: str,
        batch,
    ) -> tuple[list[RetrievedEvidence], list[dict[str, Any]]]:
        query_text = retrieval_query(
            borrower=request.borrower_name,
            application_reference=request.application_reference,
            query=query,
            request_type=f"CREDIT_MEMO_{batch.key.upper()}",
        )
        raw = self.retriever.search(
            query_vector=self.embedder.embed_text(query_text),
            application_id=request.application_id,
            top_k=min(int(batch.top_k), ApplicationFaissRetriever.MAX_PARENTS),
            candidate_k=batch.candidate_k,
        )
        packet = [self.packet_entry(item) for item in raw]
        return raw, packet

    @classmethod
    def packet_entry(cls, item: RetrievedEvidence) -> dict[str, Any]:
        if item.content_type == "PARENT_SECTION":
            return cls._parent_entry(item)
        if item.content_type == "TABLE_DATA":
            return cls._table_entry(item)
        raise ValueError(
            f"Unsupported retrieval evidence type: {item.content_type}"
        )

    @classmethod
    def _parent_entry(cls, item: RetrievedEvidence) -> dict[str, Any]:
        return {
            "source_id": item.source_id,
            "source_type": "PARENT",
            "content_type": item.content_type,
            "content_id": item.content_id,
            "parent_content_id": item.content_id,
            "chunk_id": item.chunk_id,
            "document_id": item.metadata.get("document_id"),
            "page": item.page_number,
            "page_end": item.page_end,
            "section": cls.clean_label(item.section_title),
            "document_name": cls.document_name(item),
            "text": (item.text or "").strip(),
            "related_parents": item.related_parents,
        }

    @classmethod
    def _table_entry(cls, item: RetrievedEvidence) -> dict[str, Any]:
        return {
            "source_id": item.source_id,
            "source_type": "TABLE",
            "content_type": item.content_type,
            "content_id": item.content_id,
            "parent_content_id": item.parent_content_id,
            "chunk_id": item.chunk_id,
            "table_id": item.metadata.get("table_id"),
            "document_id": item.metadata.get("document_id"),
            "page": item.page_number,
            "page_end": item.page_end,
            "section": cls.clean_label(item.section_title),
            "document_name": cls.document_name(item),
            "text": (item.text or "").strip(),
        }

    @staticmethod
    def source_id(item: RetrievedEvidence) -> str:
        return item.source_id

    @staticmethod
    def document_name(item: RetrievedEvidence) -> str:
        return (item.source_reference or "Unknown document").split(",", 1)[0].strip()

    @staticmethod
    def clean_label(value: str | None) -> str | None:
        if not value:
            return None
        ratio = sum(char.isalnum() or char.isspace() for char in value) / max(
            len(value), 1
        )
        return re.sub(r"\s+", " ", value).strip()[:160] if ratio >= 0.65 else None
