from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Document, LoanApplication


class ExtractionValidationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_document_extraction(self, document: Document) -> dict:
        path = self._extraction_path(document)
        return json.loads(path.read_text(encoding="utf-8"))

    def page(self, document: Document, page_number: int) -> dict:
        data = self.get_document_extraction(document)
        page = next(
            (
                item
                for item in data.get("pages", [])
                if item["page_number"] == page_number
            ),
            None,
        )
        if page is None:
            raise ValueError("Extracted page not found")
        return page

    def approve(self, application: LoanApplication) -> None:
        documents = list(application.documents)
        if not documents:
            raise ValueError("No documents are available")
        if any(document.extraction_status != "COMPLETED" for document in documents):
            raise ValueError("Every document must be COMPLETED before approval")
        for document in documents:
            document.extraction_status = "VALIDATED"
            document.processed_at = datetime.now(timezone.utc)
        application.status = "WAITING_FOR_CONTENT_REVIEW"
        self.session.commit()

    @staticmethod
    def _extraction_path(document: Document) -> Path:
        value = document.extraction_path or document.document_structure_path
        if not value:
            raise ValueError("Document extraction is not available")
        path = Path(value)
        if not path.exists():
            raise ValueError("Document extraction file was not found")
        return path
