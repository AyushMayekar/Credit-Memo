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
    """Retrieve child/table vectors and send at most two bounded contexts per batch."""

    def __init__(self, retriever: ApplicationFaissRetriever) -> None:
        self.retriever = retriever
        self.embedder = get_embedding_client()

    def retrieve(
        self,
        *,
        request: RetrievalRequest,
        batch,
    ) -> tuple[list[RetrievedEvidence], list[dict[str, Any]]]:
        query = retrieval_query(
            borrower=request.borrower_name,
            application_reference=request.application_reference,
            query=batch.query,
            request_type=f"CREDIT_MEMO_{batch.key.upper()}",
        )

        # `top_k` is the final number of distinct parent/table contexts.
        # `candidate_k` only widens FAISS candidate inspection and does not
        # increase the LLM prompt size.
        candidates = self.retriever.search(
            query_vector=self.embedder.embed_text(query),
            application_id=request.application_id,
            top_k=max(batch.top_k, 2),
            candidate_k=batch.candidate_k,
        )

        ranked = sorted(
            candidates,
            key=lambda item: (
                0 if item.content_type in batch.preferred_types else 1,
                -item.score,
            ),
        )

        selected: list[RetrievedEvidence] = []
        packet: list[dict[str, Any]] = []
        seen_contexts: set[tuple[str, int]] = set()

        for item in ranked:
            context_key = (
                (
                    "PARENT",
                    item.parent_content_id,
                )
                if item.parent_content_id is not None
                else (
                    item.content_type,
                    item.content_id,
                )
            )
            if context_key in seen_contexts:
                continue

            # For text vectors use the expanded parent. For table vectors use
            # the normalized table itself, which is already self-contained.
            context = (
                item.context_text if item.content_type == "CHILD_CHUNK" else item.text
            ).strip()
            prepared = self._prepare(
                context,
                item.content_type,
                batch.query,
                batch.max_evidence_characters,
            )
            if prepared is None:
                continue

            selected.append(item)
            seen_contexts.add(context_key)
            packet.append(
                {
                    "source_id": self.source_id(item),
                    "content_type": item.content_type,
                    "page": item.page_number,
                    "page_end": item.page_end,
                    "section": self.clean_label(item.section_title),
                    "document_name": self.document_name(item),
                    "text": prepared,
                    "retrieved_child_text": item.text.strip(),
                    "parent_content_id": item.parent_content_id,
                }
            )
            if len(packet) >= batch.top_k:
                break

        return selected, packet

    @staticmethod
    def _prepare(
        text: str,
        content_type: str,
        query: str,
        limit: int,
    ) -> str | None:
        if len(text) <= limit:
            return text

        # Narrative parents are never cut blindly. A parent that breaches the
        # batch budget is skipped so citations never point to partial prose.
        if content_type != "TABLE_DATA":
            return None

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 3:
            return None

        terms = {token for token in re.findall(r"[a-zA-Z]{4,}", query.casefold())}
        matching_rows = [
            line for line in lines[2:] if any(term in line.casefold() for term in terms)
        ]
        chosen = lines[:2] + matching_rows
        output: list[str] = []
        size = 0
        for line in chosen:
            if size + len(line) + 1 > limit:
                break
            output.append(line)
            size += len(line) + 1
        return "\n".join(output) if len(output) > 2 else None

    @staticmethod
    def source_id(item: RetrievedEvidence) -> str:
        return (
            f"DOC{item.metadata.get('document_id', 'X')}" f"-CONTENT-{item.content_id}"
        )

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
