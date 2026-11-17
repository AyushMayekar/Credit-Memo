from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai.retrieval.faiss_retriever import ApplicationFaissRetriever
from app.ai.retrieval.section_retriever import MemoBatchRetriever, RetrievalRequest
from app.core.config import settings
from app.db.models import LoanApplication
from app.db.session import SessionLocal
from app.services.credit_memo_batch_definitions import BATCHES


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only memo-batch retrieval test. No LLM and no writes."
    )
    parser.add_argument("--application", required=True)
    parser.add_argument("--batch", required=True)
    args = parser.parse_args()

    batch = next((item for item in BATCHES if item.key == args.batch), None)
    if batch is None:
        raise RuntimeError(f"Unknown batch: {args.batch}")

    with SessionLocal() as session:
        application = session.scalar(
            select(LoanApplication).where(
                LoanApplication.application_reference == args.application
            )
        )
        if application is None:
            raise RuntimeError("Application not found")

        index_path = (
            settings.resolve_path(settings.faiss_dir)
            / f"{settings.faiss_index_name}.faiss"
        )
        retriever = MemoBatchRetriever(ApplicationFaissRetriever(session, index_path))
        selected, packet = retriever.retrieve(
            request=RetrievalRequest(
                application.id,
                application.application_reference,
                application.borrower.legal_name,
            ),
            batch=batch,
        )

        output = {
            "batch": batch.key,
            "preferred_types": list(batch.preferred_types),
            "top_k": batch.top_k,
            "candidate_k": batch.candidate_k,
            "evidence_count": len(packet),
            "contexts": [
                {
                    "source_id": row["source_id"],
                    "content_type": row["content_type"],
                    "page": row["page"],
                    "page_end": row["page_end"],
                    "section": row["section"],
                    "parent_content_id": row["parent_content_id"],
                    "context_characters": len(row["text"]),
                    "child_preview": row["retrieved_child_text"][:500],
                    "context_preview": row["text"][:1200],
                }
                for row in packet
            ],
            "distinct_contexts": len(
                {
                    (
                        row["content_type"],
                        row["parent_content_id"] or selected[index].content_id,
                    )
                    for index, row in enumerate(packet)
                }
            ),
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
