from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, LoanApplication, ProcessingJob
from app.db.session import get_db
from app.schemas.api_models import AiPreparationRequest, JobStartRequest
from app.services.job_service import JobService
from app.services.orchestration_service import (
    run_ai_preparation_job,
    run_preparation_job,
)

router = APIRouter(tags=["Processing Jobs"])


def _job_out(job: ProcessingJob) -> dict:
    return {
        "job_reference": job.job_reference,
        "job_type": job.job_type,
        "status": job.status,
        "progress_percentage": job.progress_percentage,
        "current_stage": job.current_stage,
        "current_stage_label": job.current_stage_label,
        "message": job.message,
        "stage_details": job.stage_details,
        "result_payload": job.result_payload,
        "error_message": job.error_message,
    }


@router.post("/applications/{ref}/preparation-jobs", status_code=202)
def start_preparation(
    ref: str,
    payload: JobStartRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    application = db.scalar(
        select(LoanApplication).where(LoanApplication.application_reference == ref)
    )
    if application is None:
        raise HTTPException(404, "Application not found")
    unique_ids = list(dict.fromkeys(payload.document_ids))
    documents = list(
        db.scalars(
            select(Document).where(
                Document.application_id == application.id, Document.id.in_(unique_ids)
            )
        )
    )
    if len(documents) != len(unique_ids):
        raise HTTPException(
            404, "One or more documents do not belong to this application."
        )
    job = JobService(db).create(application.id, "EXTRACTION", document_id=None)
    job.result_payload = {
        "document_ids": unique_ids,
        "reporting_year": payload.reporting_year,
    }
    db.commit()
    db.refresh(job)
    background_tasks.add_task(run_preparation_job, job.job_reference)
    return _job_out(job)


@router.post("/applications/{ref}/ai-preparation-jobs", status_code=202)
def start_ai_preparation(
    ref: str,
    payload: AiPreparationRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    application = db.scalar(
        select(LoanApplication).where(LoanApplication.application_reference == ref)
    )
    if application is None:
        raise HTTPException(404, "Application not found")
    documents = list(
        db.scalars(
            select(Document)
            .where(
                Document.application_id == application.id,
                Document.extraction_status == "VALIDATED",
                Document.extraction_path.is_not(None),
            )
            .order_by(Document.id)
        )
    )
    if not documents:
        raise HTTPException(
            409, "Approve all document extractions before AI preparation."
        )
    job = JobService(db).create(application.id, "AI_PREPARATION", document_id=None)
    job.result_payload = {
        "document_ids": [document.id for document in documents],
        "reporting_year": payload.reporting_year,
        "process_text": True,
        "process_selected_tables": True,
        "process_selected_visuals": False,
    }
    db.commit()
    db.refresh(job)
    background_tasks.add_task(
        run_ai_preparation_job, job.job_reference, payload.reporting_year
    )
    return _job_out(job)


@router.get("/jobs/{job_ref}")
def get_job(job_ref: str, db: Session = Depends(get_db)):
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.job_reference == job_ref))
    if job is None:
        raise HTTPException(404, "Job not found")
    return _job_out(job)
