from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import LoanApplication
from app.schemas.api_models import ApplicationCreate, ApplicationPatch
from app.services.application_service import ApplicationService

router = APIRouter(prefix="/applications", tags=["Applications"])


@router.post("", status_code=201)
def create(p: ApplicationCreate, db: Session = Depends(get_db)):
    a = ApplicationService(db).create(p)
    return {"application_reference": a.application_reference, "status": a.status}


@router.get("")
def list_apps(db: Session = Depends(get_db)):
    return [
        {
            "application_reference": a.application_reference,
            "borrower_name": a.borrower.legal_name,
            "status": a.status,
        }
        for a in db.scalars(
            select(LoanApplication).order_by(LoanApplication.created_at.desc())
        )
    ]


@router.get("/{ref}")
def get(ref: str, db: Session = Depends(get_db)):
    a = ApplicationService(db).get(ref)
    if not a:
        raise HTTPException(404, "Application not found")
    return {
        "application_reference": a.application_reference,
        "borrower_name": a.borrower.legal_name,
        "status": a.status,
        "loan_amount": a.loan_amount,
        "currency": a.currency,
        "loan_purpose": a.loan_purpose,
        "tenure_months": a.tenure_months,
    }
