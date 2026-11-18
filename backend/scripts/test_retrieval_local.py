from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.ai.embedding_model import get_embedding_client
from app.ai.prompts.retrieval_prompts import retrieval_query
from app.ai.retrieval.faiss_retriever import ApplicationFaissRetriever
from app.core.config import settings
from app.db.models import LoanApplication
from app.db.session import SessionLocal
from app.services.rag_generation_service import RagGenerationService


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test child retrieval and two-parent expansion without using the UI."
    )
    parser.add_argument("--application", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Also ask the LLM and store one completed generation row.",
    )
    args = parser.parse_args()

    with SessionLocal() as session:
        application = session.scalar(
            select(LoanApplication).where(
                LoanApplication.application_reference == args.application
            )
        )
        if application is None:
            raise RuntimeError("Application not found")

        if args.with_llm:
            result = RagGenerationService(session).answer_user_query(
                application_reference=args.application,
                query=args.query,
            )
            print(json.dumps(asdict(result), indent=2, ensure_ascii=False))
            return

        query_text = retrieval_query(
            borrower=application.borrower.legal_name,
            application_reference=application.application_reference,
            query=args.query,
            request_type="USER_QUERY",
        )
        vector = get_embedding_client().embed_text(query_text)
        index_path = (
            settings.resolve_path(settings.faiss_dir)
            / f"{settings.faiss_index_name}.faiss"
        )
        evidence = ApplicationFaissRetriever(session, index_path).search(
            query_vector=vector,
            application_id=application.id,
            top_k=2,
            candidate_k=24,
        )
        output = {
            "application": args.application,
            "query": args.query,
            "evidence_count": len(evidence),
            "distinct_parent_ids": sorted(
                {
                    item.parent_content_id
                    for item in evidence
                    if item.parent_content_id is not None
                }
            ),
            "evidence": [
                {
                    "source_id": item.source_id,
                    "adjusted_score": item.score,
                    "raw_score": item.raw_score,
                    "content_type": item.content_type,
                    "content_id": item.content_id,
                    "parent_content_id": item.parent_content_id,
                    "page_number": item.page_number,
                    "page_end": item.page_end,
                    "section_title": item.section_title,
                    "chunk_id": item.chunk_id,
                    "text_preview": item.text[:1200],
                    "related_parents": item.related_parents,
                }
                for item in evidence
            ],
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
