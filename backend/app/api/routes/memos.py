from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import CreditMemo, LoanApplication
from app.db.session import get_db
from app.schemas.api_models import MemoRequest
from app.services.credit_memo_generation_service import (
    UniversalCreditMemoGenerationService,
)
from app.services.credit_memo_rendering_service import CreditMemoRenderingService

router = APIRouter(tags=["Credit Memos"])


@router.post("/applications/{ref}/credit-memos", status_code=201)
def generate(ref: str, payload: MemoRequest, db: Session = Depends(get_db)):
    try:
        r = UniversalCreditMemoGenerationService(db).generate(application_reference=ref)
        return {
            "memo_id": r.memo_id,
            "version_number": r.version_number,
            "status": r.memo_status,
            "memo": r.memo_content,
            "source_count": r.source_count,
            "quality_status": r.quality_status,
        }
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/credit-memos/{memo_id}")
def get_memo(memo_id: int, db: Session = Depends(get_db)):
    m = db.get(CreditMemo, memo_id)
    if not m:
        raise HTTPException(404, "Credit memo not found")
    return {
        "memo_id": m.id,
        "application_id": m.application_id,
        "version_number": m.version_number,
        "status": m.memo_status,
        "schema_version": m.schema_version,
        "memo": m.memo_content,
        "validation_report": m.validation_report,
        "html_available": bool(m.generated_html_path),
        "pdf_available": bool(m.generated_pdf_path),
        "created_at": m.created_at,
        "updated_at": m.updated_at,
    }


@router.get("/applications/{ref}/credit-memos")
def list_memos(ref: str, db: Session = Depends(get_db)):
    a = db.scalar(
        select(LoanApplication).where(LoanApplication.application_reference == ref)
    )
    if not a:
        raise HTTPException(404, "Application not found")
    return [
        {
            "memo_id": m.id,
            "version_number": m.version_number,
            "status": m.memo_status,
            "schema_version": m.schema_version,
            "quality_status": (
                m.memo_content.get("missing_information_and_quality_flags") or {}
            ).get("overall_quality_status"),
            "created_at": m.created_at,
        }
        for m in db.scalars(
            select(CreditMemo)
            .where(CreditMemo.application_id == a.id)
            .order_by(CreditMemo.version_number.desc())
        )
    ]


@router.get("/credit-memos/{memo_id}/preview", response_class=HTMLResponse)
def preview(memo_id: int, db: Session = Depends(get_db)):
    m = db.get(CreditMemo, memo_id)
    if not m:
        raise HTTPException(404, "Credit memo not found")
    path = CreditMemoRenderingService().render_html(m)
    db.commit()
    return HTMLResponse(path.read_text(encoding="utf-8"))


@router.post("/credit-memos/{memo_id}/exports/pdf")
def export_pdf(memo_id: int, db: Session = Depends(get_db)):
    m = db.get(CreditMemo, memo_id)
    if not m:
        raise HTTPException(404, "Credit memo not found")
    try:
        path = CreditMemoRenderingService().render_pdf(m)
        db.commit()
        return {
            "memo_id": m.id,
            "status": "READY",
            "download_url": f"/api/v1/credit-memos/{m.id}/exports/pdf",
        }
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/credit-memos/{memo_id}/exports/pdf")
def download_pdf(
    memo_id: int,
    db: Session = Depends(get_db),
):
    memo = db.get(CreditMemo, memo_id)

    if (
        memo is None
        or not memo.generated_pdf_path
        or not Path(memo.generated_pdf_path).exists()
    ):
        raise HTTPException(
            status_code=404,
            detail="Generated PDF not found",
        )

    pdf_path = Path(memo.generated_pdf_path)

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"credit_memo_v{memo.version_number}.pdf",
        headers={
            "Cache-Control": ("no-store, no-cache, must-revalidate, " "max-age=0"),
            "Pragma": "no-cache",
            "Expires": "0",
            "ETag": f'"{pdf_path.stat().st_mtime_ns}"',
        },
    )
