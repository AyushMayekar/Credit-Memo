from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from sqlalchemy import select

from app.ai.embedding_model import get_embedding_client
from app.ai.retrieval.faiss_retriever import ApplicationFaissRetriever
from app.core.config import settings
from app.db.models import LoanApplication


def _object_to_dict(value: Any) -> dict[str, Any]:
    """Normalize project result objects without converting them to strings."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python")
    if hasattr(value, "dict") and callable(value.dict):
        return value.dict()
    if hasattr(value, "__dict__"):
        return {k: v for k, v in vars(value).items() if not k.startswith("_")}
    raise TypeError(f"Unsupported result type: {type(value)!r}")


class Adapter:
    def __init__(self, session):
        self.s = session
        self.app = None

    def load(self, reference: str):
        self.app = self.s.scalar(
            select(LoanApplication).where(
                LoanApplication.application_reference == reference
            )
        )
        if not self.app:
            raise RuntimeError("Application not found")

    def retrieve(self, question: str):
        query_vector = get_embedding_client().embed_text(question)
        index_path = (
            settings.resolve_path(settings.faiss_dir)
            / f"{settings.faiss_index_name}.faiss"
        )
        return list(
            ApplicationFaissRetriever(self.s, index_path).search(
                query_vector=query_vector,
                application_id=self.app.id,
                top_k=2,
                candidate_k=24,
            )
        )

    def answer(self, question: str) -> dict[str, Any]:
        """Return the real RAG response and top-level source metadata.

        The previous adapter wrapped GenerationResult in str(...), causing every
        sources_present check to fail even when GenerationResult.sources existed.
        """
        from app.services.rag_generation_service import RagGenerationService

        result = RagGenerationService(self.s).answer_user_query(
            application_reference=self.app.application_reference,
            query=question,
        )
        normalized = _object_to_dict(result)

        response = normalized.get("response", normalized)
        response = _object_to_dict(response)

        top_sources = normalized.get("sources") or []
        response_sources = response.get("sources") or []
        response["sources"] = top_sources or response_sources

        if normalized.get("generation_id") is not None:
            response["generation_id"] = normalized["generation_id"]
        if normalized.get("route") is not None:
            response["route"] = normalized["route"]

        return response

    def new_memo(self):
        from app.services.credit_memo_generation_service import (
            UniversalCreditMemoGenerationService,
        )

        service = UniversalCreditMemoGenerationService(self.s)
        if not hasattr(service, "generate_read_only"):
            raise RuntimeError(
                "Add generate_read_only(application_reference) returning the "
                "canonical memo without persistence."
            )
        return service.generate_read_only(
            application_reference=self.app.application_reference
        )
