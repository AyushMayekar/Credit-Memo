from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import UploadFile
from app.db.models import Document, LoanApplication
from app.services.storage_service import StorageService


class UploadService:
    def __init__(self, s: Session):
        self.s = s
        self.storage = StorageService()

    def upload(self, ref: str, file: UploadFile):
        app = self.s.scalar(
            select(LoanApplication).where(LoanApplication.application_reference == ref)
        )
        if not app:
            raise ValueError("Application not found")
        tmp = self.storage.upload_root / "_incoming" / file.filename
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                out.write(chunk)
        try:
            stored = self.storage.store_pdf(
                tmp, ref, file.content_type or "application/pdf"
            )
        finally:
            tmp.unlink(missing_ok=True)
        doc = Document(
            application_id=app.id,
            original_filename=stored.original_filename,
            stored_filename=stored.stored_filename,
            storage_path=stored.storage_path,
            mime_type=stored.mime_type,
            file_size_bytes=stored.file_size_bytes,
            file_hash=stored.file_hash,
            extraction_status="PENDING",
        )
        self.s.add(doc)
        app.status = "DOCUMENTS_UPLOADED"
        self.s.commit()
        self.s.refresh(doc)
        return doc
