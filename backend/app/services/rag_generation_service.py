from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.ai.retrieval.faiss_retriever import ApplicationFaissRetriever
from app.ai.retrieval.workflow import RagWorkflow
from app.core.config import settings
from app.db.models import RagGeneration

CREDIT_MEMO_REQUEST = "Prepare a grounded credit memo evidence draft for this application using the most relevant indexed evidence. Do not invent missing information."


@dataclass(frozen=True, slots=True)
class GenerationResult:
    generation_id: int
    route: str
    response: dict[str, Any]
    sources: list[dict[str, Any]]


class RagGenerationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        index_path = (
            settings.resolve_path(settings.faiss_dir)
            / f"{settings.faiss_index_name}.faiss"
        )
        self.workflow = RagWorkflow(
            session, ApplicationFaissRetriever(session, index_path)
        )

    def answer_user_query(
        self, *, application_reference: str, query: str
    ) -> GenerationResult:
        return self._run(
            application_reference=application_reference,
            query=query,
            request_type="USER_QUERY",
            predefined_prompt_key=None,
        )

    def generate_credit_memo(self, *, application_reference: str) -> GenerationResult:
        return self._run(
            application_reference=application_reference,
            query=CREDIT_MEMO_REQUEST,
            request_type="CREDIT_MEMO",
            predefined_prompt_key="CREDIT_MEMO_V2",
        )

    def _run(
        self,
        *,
        application_reference: str,
        query: str,
        request_type: str,
        predefined_prompt_key: str | None,
    ) -> GenerationResult:
        state = self.workflow.invoke(
            application_reference=application_reference,
            query=query,
            request_type=request_type,
        )
        route = state["route"]
        if route in {"APP_HELP", "OUT_OF_SCOPE"}:
            # Application-help and refusal paths deliberately do not touch
            # PostgreSQL, FAISS, or the generation history table.
            return GenerationResult(0, route, state["response"], [])
        evidence = state.get("evidence", [])
        sources = [
            {
                "source_id": item.source_id,
                "score": item.score,
                "raw_score": item.raw_score,
                "content_id": item.content_id,
                "parent_content_id": item.parent_content_id,
                "content_type": item.content_type,
                "document_id": item.metadata.get("document_id"),
                "chunk_id": item.chunk_id,
                "page_number": item.page_number,
                "page_end": item.page_end,
                "section_title": item.section_title,
                "source_reference": item.source_reference,
                "table_image_path": item.table_image_path,
                "visual_image_path": item.visual_image_path,
            }
            for item in evidence
        ]
        record = RagGeneration(
            application_id=state["application_id"],
            request_type=request_type,
            route=route,
            user_query=query if request_type == "USER_QUERY" else None,
            predefined_prompt_key=predefined_prompt_key,
            response_json=state["response"],
            source_snapshot=sources,
            status="COMPLETED",
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return GenerationResult(record.id, state["route"], state["response"], sources)
