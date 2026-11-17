from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import Document, LoanApplication
from app.services.upload_service import UploadService

router = APIRouter(tags=["Documents"])


@router.post("/applications/{ref}/documents", status_code=201)
def upload(ref: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        d = UploadService(db).upload(ref, file)
        return {
            "document_id": d.id,
            "filename": d.original_filename,
            "status": "UPLOADED",
        }
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/applications/{ref}/documents")
def list_docs(ref: str, db: Session = Depends(get_db)):
    a = db.scalar(
        select(LoanApplication).where(LoanApplication.application_reference == ref)
    )
    if not a:
        raise HTTPException(404, "Application not found")
    return [
        {
            "document_id": d.id,
            "filename": d.original_filename,
            "status": d.extraction_status,
            "page_count": d.page_count,
        }
        for d in a.documents
    ]


@router.get("/documents/{document_id}/file")
def file(document_id: int, db: Session = Depends(get_db)):
    d = db.get(Document, document_id)
    if not d or not Path(d.storage_path).exists():
        raise HTTPException(404, "Document file not found")
    return FileResponse(
        d.storage_path, media_type="application/pdf", filename=d.original_filename
    )
