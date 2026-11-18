from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai.retrieval.section_retriever import RetrievalRequest
from app.db.models import LoanApplication
from app.db.session import SessionLocal
from app.services.credit_memo_batch_definitions import BATCHES
from app.services.credit_memo_extraction_service import CreditMemoExtractionService


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
        request = RetrievalRequest(
            application.id,
            application.application_reference,
            application.borrower.legal_name,
        )
        facts = {
            "borrower_name": application.borrower.legal_name,
            "facility_amount": float(application.loan_amount),
            "currency": application.currency,
            "tenure_months": application.tenure_months,
        }

    result, sources, audit = CreditMemoExtractionService()._run_batch(
        request,
        facts,
        batch,
    )
    print(
        json.dumps(
            {
                "batch": batch.key,
                "audit": audit,
                "sources": list(sources.values()),
                "result": result,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
