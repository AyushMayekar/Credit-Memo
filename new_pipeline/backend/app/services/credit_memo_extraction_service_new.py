from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from app.ai.llm import get_llm
from app.ai.prompts.credit_memo_prompts import (
    build_batch_messages,
    build_output_contract,
)
from app.ai.retrieval.faiss_retriever import ApplicationFaissRetriever
from app.ai.retrieval.section_agent import run_batch_with_threads
from app.core.config import settings
from app.db.session import SessionLocal
from app.services.credit_memo_batch_definitions import BATCHES


class CreditMemoExtractionService:
    MAX_CONCURRENCY = 5  # 5 worker threads

    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or SessionLocal

    def extract_all(
        self,
        *,
        application_reference: str,
        query: str,
        request_type: str,
    ) -> dict[str, Any]:
        """Extract all batches for a given application/query.

        Returns a dict with per-batch results ready for combine/assembly.
        """
        # Find the application
        from app.db.models import LoanApplication
        from sqlalchemy import select

        session = self.session_factory()
        try:
            app = session.scalar(
                select(LoanApplication).where(
                    LoanApplication.application_reference == application_reference
                )
            )
            if app is None:
                return {"error": "Application not found", "batch_results": {}}

            # Build batch configs
            batch_configs = []
            for batch in BATCHES:
                batch_configs.append(
                    {
                        "application_id": app.id,
                        "borrower_name": app.borrower.legal_name,
                        "application_reference": application_reference,
                        "query": query,
                        "request_type": request_type,
                        "batch_key": batch.key,
                        "retriever": ApplicationFaissRetriever(
                            session,
                            settings.resolve_path(settings.faiss_dir)
                            / f"{settings.faiss_index_name}.faiss",
                        ),
                    }
                )

            # Run all batches with 5 workers
            results = run_all_batches(
                batch_configs=batch_configs,
                session_factory=self.session_factory,
                max_workers=self.MAX_CONCURRENCY,
            )

            return {
                "error": None,
                "batch_results": results,
                "application_reference": application_reference,
                "query": query,
                "request_type": request_type,
            }
        except Exception as exc:
            return {"error": str(exc), "batch_results": {}}
        finally:
            try:
                session.close()
            except Exception:
                pass
