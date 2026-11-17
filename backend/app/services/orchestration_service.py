from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path

from sqlalchemy import select

from app.ai.extraction.standalone_hybrid_extractor_v4 import (
    StandaloneHybridExtractorV4,
)
from app.ai.parsing.unified_parsing_pipeline import UnifiedParsingPipeline
from app.core.config import PROJECT_ROOT
from app.db.models import Document, LoanApplication, ProcessingJob
from app.db.session import SessionLocal
from app.services.batch_content_ingestion_service import BatchContentIngestionService
from app.services.job_service import JobService


def _job_document_ids(job: ProcessingJob) -> list[int]:
    payload = job.result_payload or {}
    values = payload.get("document_ids") or (
        [job.document_id] if job.document_id else []
    )
    return [int(value) for value in values]


def _progress(done: int, total: int, start: int, end: int) -> int:
    if total <= 0:
        return end
    return min(end, start + round(done / total * (end - start)))


def run_preparation_job(job_ref: str) -> None:
    with SessionLocal() as session:
        jobs = JobService(session)
        job = session.scalar(
            select(ProcessingJob).where(ProcessingJob.job_reference == job_ref)
        )
        if not job:
            return
        application = session.get(LoanApplication, job.application_id)
        document_ids = _job_document_ids(job)
        documents = list(
            session.scalars(
                select(Document)
                .where(
                    Document.application_id == job.application_id,
                    Document.id.in_(document_ids),
                )
                .order_by(Document.id)
            )
        )
        if not application or not documents:
            jobs.update(
                job_ref,
                status="FAILED",
                stage="FAILED",
                label="Document extraction failed",
                error="No matching uploaded documents were found.",
            )
            return
        results = []
        try:
            application.status = "PREPARING_DOCUMENTS"
            session.commit()
            extractor = StandaloneHybridExtractorV4(
                output_root=PROJECT_ROOT / "storage" / "extracted",
                artifacts_path=PROJECT_ROOT / "docling_models",
            )
            for index, document in enumerate(documents, start=1):
                jobs.update(
                    job_ref,
                    status="RUNNING",
                    progress=_progress(index - 1, len(documents), 5, 92),
                    stage="EXTRACTING",
                    label=f"Extracting document {index} of {len(documents)}",
                    message=f"Extracting lossless Docling text and layout from {document.original_filename}.",
                )
                document.extraction_status = "PROCESSING"
                document.extraction_error = None
                session.commit()
                period_end = document.reporting_period_end or date.today()
                result = extractor.extract(
                    pdf_path=Path(document.storage_path),
                    application_reference=application.application_reference,
                    document_reference=f"DOC-{document.id:06d}",
                    document_name=document.original_filename,
                    period_type="annual",
                    period_end=period_end,
                    period_label=f"FY{period_end.year}",
                )
                document.extraction_path = result.extraction_path
                document.extraction_summary_path = result.summary_path
                document.document_structure_path = result.extraction_path
                document.page_count = result.page_count
                document.extraction_status = "COMPLETED"
                session.commit()
                results.append(
                    {
                        "document_id": document.id,
                        "filename": document.original_filename,
                        "status": "COMPLETED",
                        "result": asdict(result),
                    }
                )
            application.status = "WAITING_FOR_CONTENT_REVIEW"
            session.commit()
            jobs.update(
                job_ref,
                status="COMPLETED",
                progress=100,
                stage="WAITING_FOR_VALIDATION",
                label="Extraction ready for validation",
                message=f"Lossless Docling text and layout were extracted from {len(documents)} document(s). Review the output before continuing.",
                result={"document_ids": document_ids, "documents": results},
            )
        except Exception as exc:
            session.rollback()
            application = session.get(LoanApplication, job.application_id)
            if application:
                application.status = "FAILED"
                session.commit()
            jobs.update(
                job_ref,
                status="FAILED",
                stage="FAILED",
                label="Document extraction failed",
                error=str(exc),
                result={"document_ids": document_ids, "documents": results},
            )


def run_ai_preparation_job(job_ref: str, reporting_year: str | None) -> None:
    with SessionLocal() as session:
        jobs = JobService(session)
        job = session.scalar(
            select(ProcessingJob).where(ProcessingJob.job_reference == job_ref)
        )
        if not job:
            return
        application = session.get(LoanApplication, job.application_id)
        document_ids = _job_document_ids(job)
        documents = list(
            session.scalars(
                select(Document)
                .where(
                    Document.application_id == job.application_id,
                    Document.id.in_(document_ids),
                    Document.extraction_status == "VALIDATED",
                )
                .order_by(Document.id)
            )
        )
        if not application or len(documents) != len(document_ids):
            jobs.update(
                job_ref,
                status="FAILED",
                stage="FAILED",
                label="AI preparation failed",
                error="Every selected document must have a validated extraction.",
            )
            return
        try:
            application.status = "PREPARING_AI"
            session.commit()
            parser = UnifiedParsingPipeline(
                parsed_root=PROJECT_ROOT / "storage" / "parsed-v8"
            )
            parse_results = []
            for index, document in enumerate(documents, start=1):
                jobs.update(
                    job_ref,
                    status="RUNNING",
                    progress=_progress(index - 1, len(documents), 5, 38),
                    stage="PARSING",
                    label=f"Structurally parsing document {index} of {len(documents)}",
                    message="Building sections, normalized tables, and source-grounded records.",
                )
                extraction_path = Path(
                    document.extraction_path or document.document_structure_path
                )
                result = parser.parse(
                    extraction_path=extraction_path,
                    application_reference=application.application_reference,
                    document_reference=f"DOC-{document.id:06d}",
                )
                document.parsed_output_path = result.output_directory
                document.parsed_document_path = result.parsed_document_path
                document.parser_summary_path = result.parser_summary_path
                session.commit()
                parse_results.append(asdict(result))

            jobs.update(
                job_ref,
                status="RUNNING",
                progress=42,
                stage="CHUNKING",
                label="Preparing searchable evidence",
                message="Creating parent sections, child chunks, and structured table chunks.",
            )
            jobs.update(
                job_ref,
                status="RUNNING",
                progress=52,
                stage="EMBEDDING",
                label="Generating embeddings",
                message="Sending token-safe embedding batches and preparing the cosine index.",
            )
            ingestion = BatchContentIngestionService(session).ingest_application(
                application_reference=application.application_reference,
                document_ids=document_ids,
                reporting_year=reporting_year,
                replace_existing=True,
            )
            application = session.get(LoanApplication, job.application_id)
            application.status = "AI_READY"
            session.commit()
            jobs.update(
                job_ref,
                status="COMPLETED",
                progress=100,
                stage="AI_READY",
                label="Documents are ready for AI",
                message=f"Indexed {ingestion.text_count} text chunks and {ingestion.table_count} tables in {ingestion.embedding_request_count} embedding requests.",
                result={
                    "document_ids": document_ids,
                    "reporting_year": reporting_year,
                    "parsing": parse_results,
                    "ingestion": asdict(ingestion),
                },
            )
        except Exception as exc:
            session.rollback()
            application = session.get(LoanApplication, job.application_id)
            if application:
                application.status = "FAILED"
                session.commit()
            jobs.update(
                job_ref,
                status="FAILED",
                stage="FAILED",
                label="AI preparation failed",
                error=str(exc),
                result={"document_ids": document_ids, "reporting_year": reporting_year},
            )
