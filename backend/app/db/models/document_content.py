from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.document import Document
    from app.db.models.extracted_image import ExtractedImage
    from app.db.models.extracted_table import ExtractedTable
    from app.db.models.faiss_vector_mapping import FaissVectorMapping
    from app.db.models.loan_application import LoanApplication


class DocumentContent(Base):
    __tablename__ = "document_contents"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.loan_applications.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.documents.id", ondelete="CASCADE"), nullable=False
    )
    parent_content_id: Mapped[int | None] = mapped_column(
        ForeignKey("credit_ai.document_contents.id", ondelete="SET NULL")
    )
    content_type: Mapped[str] = mapped_column(String(30), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    chunk_order: Mapped[int | None] = mapped_column(Integer)
    chunk_index: Mapped[int | None] = mapped_column(Integer)
    section_title: Mapped[str | None] = mapped_column(Text)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_text: Mapped[str | None] = mapped_column(Text)
    search_summary: Mapped[str | None] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer)
    chunking_strategy: Mapped[str | None] = mapped_column(String(80))
    content_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    reporting_year: Mapped[str | None] = mapped_column(String(20))
    financial_topic: Mapped[str | None] = mapped_column(String(100))
    source_reference: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    application: Mapped["LoanApplication"] = relationship(
        back_populates="document_contents"
    )
    document: Mapped["Document"] = relationship(back_populates="contents")
    parent: Mapped["DocumentContent | None"] = relationship(
        remote_side=[id], back_populates="children"
    )
    children: Mapped[list["DocumentContent"]] = relationship(back_populates="parent")
    faiss_mappings: Mapped[list["FaissVectorMapping"]] = relationship(
        back_populates="content", cascade="all, delete-orphan"
    )
    extracted_tables: Mapped[list["ExtractedTable"]] = relationship(
        back_populates="content"
    )
    extracted_images: Mapped[list["ExtractedImage"]] = relationship(
        back_populates="content"
    )
