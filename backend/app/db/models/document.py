from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.document_content import DocumentContent
    from app.db.models.extracted_image import ExtractedImage
    from app.db.models.extracted_table import ExtractedTable
    from app.db.models.faiss_vector_mapping import FaissVectorMapping
    from app.db.models.financial_value import FinancialValue
    from app.db.models.loan_application import LoanApplication


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.loan_applications.id", ondelete="CASCADE"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_path: Mapped[str | None] = mapped_column(Text)
    extraction_summary_path: Mapped[str | None] = mapped_column(Text)
    parsed_output_path: Mapped[str | None] = mapped_column(Text)
    parsed_document_path: Mapped[str | None] = mapped_column(Text)
    document_structure_path: Mapped[str | None] = mapped_column(Text)
    parser_summary_path: Mapped[str | None] = mapped_column(Text)
    document_type: Mapped[str | None] = mapped_column(String(100))
    mime_type: Mapped[str] = mapped_column(
        String(100), nullable=False, default="application/pdf"
    )
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    file_hash: Mapped[str | None] = mapped_column(String(128))
    page_count: Mapped[int | None] = mapped_column(Integer)
    reporting_period_start: Mapped[date | None] = mapped_column(Date)
    reporting_period_end: Mapped[date | None] = mapped_column(Date)
    extraction_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PENDING"
    )
    extraction_error: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    application: Mapped["LoanApplication"] = relationship(back_populates="documents")
    contents: Mapped[list["DocumentContent"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    faiss_vector_mappings: Mapped[list["FaissVectorMapping"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    extracted_tables: Mapped[list["ExtractedTable"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    extracted_images: Mapped[list["ExtractedImage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    financial_values: Mapped[list["FinancialValue"]] = relationship(
        back_populates="document"
    )
