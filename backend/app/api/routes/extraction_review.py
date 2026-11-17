from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, LoanApplication
from app.db.session import get_db
from app.services.extraction_validation_service import ExtractionValidationService

router = APIRouter(tags=["Extraction Validation"])


@router.get("/applications/{ref}/extractions")
def list_extractions(ref: str, db: Session = Depends(get_db)):
    application = db.scalar(
        select(LoanApplication).where(LoanApplication.application_reference == ref)
    )
    if application is None:
        raise HTTPException(404, "Application not found")
    return [
        {
            "document_id": d.id,
            "filename": d.original_filename,
            "status": d.extraction_status,
            "page_count": d.page_count,
            "extraction_available": bool(
                d.extraction_path or d.document_structure_path
            ),
        }
        for d in application.documents
    ]


@router.get("/documents/{document_id}/extraction")
def get_extraction(document_id: int, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "Document not found")
    try:
        return ExtractionValidationService(db).get_document_extraction(document)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/documents/{document_id}/extraction/pages/{page_number}")
def get_extraction_page(
    document_id: int, page_number: int, db: Session = Depends(get_db)
):
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "Document not found")
    try:
        return ExtractionValidationService(db).page(document, page_number)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/applications/{ref}/extractions/approve")
def approve_extractions(ref: str, db: Session = Depends(get_db)):
    application = db.scalar(
        select(LoanApplication).where(LoanApplication.application_reference == ref)
    )
    if application is None:
        raise HTTPException(404, "Application not found")
    try:
        ExtractionValidationService(db).approve(application)
        return {
            "status": "VALIDATED",
            "message": "Extraction approved. The documents can now be prepared for AI search.",
        }
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
