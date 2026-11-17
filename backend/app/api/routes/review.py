from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import ContentReviewItem, LoanApplication
from app.schemas.api_models import SelectionPatch
from app.services.content_review_service import ContentReviewService

router = APIRouter(tags=["Content Review"])


@router.get("/applications/{ref}/content-review")
def summary(ref: str, db: Session = Depends(get_db)):
    a = db.scalar(
        select(LoanApplication).where(LoanApplication.application_reference == ref)
    )
    if not a:
        raise HTTPException(404, "Application not found")
    items = list(
        db.scalars(
            select(ContentReviewItem).where(ContentReviewItem.application_id == a.id)
        )
    )
    return {
        "status": a.status,
        "table_count": sum(x.item_type == "TABLE" for x in items),
        "visual_count": sum(x.item_type == "VISUAL" for x in items),
        "selected_table_count": sum(
            x.item_type == "TABLE" and x.selected_for_analysis for x in items
        ),
        "selected_visual_count": sum(
            x.item_type == "VISUAL" and x.selected_for_analysis for x in items
        ),
    }


@router.get("/applications/{ref}/review-items")
def items(ref: str, item_type: str | None = None, db: Session = Depends(get_db)):
    a = db.scalar(
        select(LoanApplication).where(LoanApplication.application_reference == ref)
    )
    q = select(ContentReviewItem).where(ContentReviewItem.application_id == a.id)
    if item_type:
        q = q.where(ContentReviewItem.item_type == item_type.upper())
    return [
        {
            "id": x.id,
            "type": x.item_type,
            "reference": x.item_reference,
            "page_number": x.page_number,
            "section_title": x.section_title,
            "quality_status": x.quality_status,
            "selected_for_analysis": x.selected_for_analysis,
            "preview_url": f"/api/v1/review-items/{x.id}/preview",
        }
        for x in db.scalars(q.order_by(ContentReviewItem.page_number))
    ]


@router.patch("/review-items/{item_id}/selection")
def patch(item_id: int, p: SelectionPatch, db: Session = Depends(get_db)):
    try:
        x = ContentReviewService(db).patch(item_id, p.selected_for_analysis, p.reason)
        return {"id": x.id, "selected_for_analysis": x.selected_for_analysis}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/review-items/{item_id}/preview")
def preview(item_id: int, db: Session = Depends(get_db)):
    x = db.get(ContentReviewItem, item_id)
    if not x or not x.preview_path or not Path(x.preview_path).exists():
        raise HTTPException(404, "Preview not found")
    return FileResponse(x.preview_path, media_type="image/png")


@router.post("/applications/{ref}/content-review/finalize")
def finalize(ref: str, db: Session = Depends(get_db)):
    a = db.scalar(
        select(LoanApplication).where(LoanApplication.application_reference == ref)
    )
    if not a:
        raise HTTPException(404, "Application not found")
    return {"status": "REVIEW_COMPLETED", "next_action": "START_AI_PREPARATION"}
