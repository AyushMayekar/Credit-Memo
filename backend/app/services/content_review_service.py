import json
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.db.models import ContentReviewItem, Document, LoanApplication


class ContentReviewService:
    def __init__(self, s: Session):
        self.s = s

    def create_from_structure(self, app_id: int, doc: Document):
        data = json.loads(Path(doc.document_structure_path).read_text(encoding="utf-8"))
        self.s.execute(
            delete(ContentReviewItem).where(ContentReviewItem.document_id == doc.id)
        )
        for t in data.get("tables", []):
            self.s.add(
                ContentReviewItem(
                    application_id=app_id,
                    document_id=doc.id,
                    item_type="TABLE",
                    item_reference=t["table_id"],
                    page_number=t["page_number"],
                    section_title=t.get("section_title"),
                    preview_path=t.get("image_path"),
                    source_payload=t,
                    quality_status=t.get("quality_classification", "TABLE"),
                    selected_for_analysis=True,
                )
            )
        for v in data.get("visuals", []) + data.get("visuals_requiring_review", []):
            self.s.add(
                ContentReviewItem(
                    application_id=app_id,
                    document_id=doc.id,
                    item_type="VISUAL",
                    item_reference=v["visual_id"],
                    page_number=v["page_number"],
                    section_title=v.get("section_title"),
                    preview_path=v.get("image_path"),
                    source_payload=v,
                    quality_status=v.get("filter_decision", "ACCEPTED"),
                    selected_for_analysis=v.get("filter_decision") == "ACCEPTED",
                )
            )
        self.s.commit()

    def patch(self, item_id: int, selected: bool, reason: str | None):
        item = self.s.get(ContentReviewItem, item_id)
        if not item:
            raise ValueError("Review item not found")
        item.selected_for_analysis = selected
        item.excluded_by_user = not selected
        item.exclusion_reason = reason
        item.reviewed_at = datetime.now(timezone.utc)
        self.s.commit()
        self.s.refresh(item)
        return item

    def selected_payload(self, doc: Document):
        data = json.loads(Path(doc.document_structure_path).read_text(encoding="utf-8"))
        items = list(
            self.s.scalars(
                select(ContentReviewItem).where(
                    ContentReviewItem.document_id == doc.id,
                    ContentReviewItem.selected_for_analysis.is_(True),
                )
            )
        )
        table_ids = {x.item_reference for x in items if x.item_type == "TABLE"}
        visual_ids = {x.item_reference for x in items if x.item_type == "VISUAL"}
        data["tables"] = [
            x for x in data.get("tables", []) if x["table_id"] in table_ids
        ]
        all_visuals = data.get("visuals", []) + data.get("visuals_requiring_review", [])
        data["visuals"] = [x for x in all_visuals if x["visual_id"] in visual_ids]
        data["visuals_requiring_review"] = []
        out = Path(doc.parsed_output_path) / "document_structure_selected.json"
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return out
