from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import (
    Document,
    DocumentContent,
    ExtractedImage,
    ExtractedTable,
    LoanApplication,
)


class DocumentRepository:
    """Database operations used by the document-ingestion workflow."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_application_by_reference(
        self,
        application_reference: str,
    ) -> LoanApplication | None:
        return self.session.scalar(
            select(LoanApplication).where(
                LoanApplication.application_reference == application_reference
            )
        )

    def find_document_by_hash(
        self,
        application_id: int,
        file_hash: str,
    ) -> Document | None:
        return self.session.scalar(
            select(Document).where(
                Document.application_id == application_id,
                Document.file_hash == file_hash,
            )
        )

    def create_document(
        self,
        *,
        application_id: int,
        original_filename: str,
        stored_filename: str,
        storage_path: str,
        mime_type: str,
        file_size_bytes: int,
        file_hash: str,
    ) -> Document:
        document = Document(
            application_id=application_id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            storage_path=storage_path,
            mime_type=mime_type,
            file_size_bytes=file_size_bytes,
            file_hash=file_hash,
            extraction_status="PENDING",
        )
        self.session.add(document)
        self.session.flush()
        return document

    def replace_extracted_content(self, document_id: int) -> None:
        """Delete prior parsed records before a controlled re-ingestion."""
        self.session.execute(
            delete(ExtractedImage).where(ExtractedImage.document_id == document_id)
        )
        self.session.execute(
            delete(ExtractedTable).where(ExtractedTable.document_id == document_id)
        )
        self.session.execute(
            delete(DocumentContent).where(DocumentContent.document_id == document_id)
        )

    def add_content(self, content: DocumentContent) -> None:
        self.session.add(content)

    def add_table(self, table: ExtractedTable) -> None:
        self.session.add(table)

    def add_image(self, image: ExtractedImage) -> None:
        self.session.add(image)
