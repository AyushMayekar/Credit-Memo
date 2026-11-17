from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import ProcessingJob, LoanApplication


class JobService:
    def __init__(self, s: Session):
        self.s = s

    def create(self, app_id: int, job_type: str, document_id: int | None = None):
        j = ProcessingJob(
            job_reference=f"JOB-{uuid4().hex[:12].upper()}",
            application_id=app_id,
            document_id=document_id,
            job_type=job_type,
            status="QUEUED",
            stage_details=[],
        )
        self.s.add(j)
        self.s.commit()
        self.s.refresh(j)
        return j

    def update(
        self,
        ref,
        *,
        status=None,
        progress=None,
        stage=None,
        label=None,
        message=None,
        result=None,
        error=None,
    ):
        j = self.s.scalar(
            select(ProcessingJob).where(ProcessingJob.job_reference == ref)
        )
        if not j:
            return
        if status:
            j.status = status
        if progress is not None:
            j.progress_percentage = progress
        if stage:
            j.current_stage = stage
        if label:
            j.current_stage_label = label
        if message is not None:
            j.message = message
        if result is not None:
            j.result_payload = result
        if error is not None:
            j.error_message = error
        if status == "RUNNING" and not j.started_at:
            j.started_at = datetime.now(timezone.utc)
        if status in {"COMPLETED", "FAILED", "CANCELLED"}:
            j.completed_at = datetime.now(timezone.utc)
        self.s.commit()
