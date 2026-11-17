from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai.llm import get_llm
from app.ai.prompts.credit_memo_prompts import build_batch_messages
from app.ai.retrieval.faiss_retriever import ApplicationFaissRetriever
from app.ai.retrieval.json_utils import parse_json_object
from app.ai.retrieval.section_retriever import MemoBatchRetriever, RetrievalRequest
from app.core.config import settings
from app.db.models import LoanApplication
from app.db.session import SessionLocal
from app.services.credit_memo_batch_definitions import BATCHES


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one memo batch without creating a credit memo."
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
        _, packet = retriever.retrieve(
            request=RetrievalRequest(
                application.id,
                application.application_reference,
                application.borrower.legal_name,
            ),
            batch=batch,
        )
        facts = {
            "borrower_name": application.borrower.legal_name,
            "facility_amount": float(application.loan_amount),
            "currency": application.currency,
            "tenure_months": application.tenure_months,
        }

    if not packet:
        print(json.dumps({"batch": batch.key, "status": "NO_EVIDENCE"}, indent=2))
        return

    messages, contract, aliases = build_batch_messages(
        batch=batch,
        application_facts=facts,
        evidence=packet,
    )
    response = get_llm().chat_response(
        messages,
        temperature=0,
        max_tokens=batch.max_output_tokens,
    )
    result = parse_json_object(response.content)
    errors = [
        error.message for error in Draft202012Validator(contract).iter_errors(result)
    ]
    print(
        json.dumps(
            {
                "batch": batch.key,
                "finish_reason": response.finish_reason,
                "evidence_count": len(packet),
                "evidence": [
                    {
                        "alias": f"S{index}",
                        "source_id": row["source_id"],
                        "type": row["content_type"],
                        "page": row["page"],
                        "parent_content_id": row["parent_content_id"],
                        "characters": len(row["text"]),
                    }
                    for index, row in enumerate(packet, start=1)
                ],
                "aliases": aliases,
                "validation_errors": errors,
                "response": result,
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    if response.finish_reason in {"length", "max_tokens"} or errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
