from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.document import Document
    from app.db.models.document_content import DocumentContent
    from app.db.models.loan_application import LoanApplication
    from app.db.models.financial_value import FinancialValue


class ExtractedTable(Base):
    __tablename__ = "extracted_tables"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.loan_applications.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.documents.id", ondelete="CASCADE"), nullable=False
    )
    content_id: Mapped[int | None] = mapped_column(
        ForeignKey("credit_ai.document_contents.id", ondelete="SET NULL")
    )
    table_reference: Mapped[str] = mapped_column(String(50), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    section_id: Mapped[str | None] = mapped_column(String(50))
    section_title: Mapped[str | None] = mapped_column(Text)
    bounding_box: Mapped[list[Any] | None] = mapped_column(JSONB)
    original_rows: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    normalized_rows: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    table_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    json_path: Mapped[str | None] = mapped_column(Text)
    markdown_path: Mapped[str | None] = mapped_column(Text)
    image_path: Mapped[str | None] = mapped_column(Text)
    nearby_text: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    generated_title: Mapped[str | None] = mapped_column(Text)
    generated_summary: Mapped[str | None] = mapped_column(Text)
    reporting_periods: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    units: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    important_facts: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    financial_topics: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    uncertainties: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    quality_score: Mapped[float | None] = mapped_column(Float)
    quality_classification: Mapped[str | None] = mapped_column(String(40))
    review_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    context_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PENDING"
    )
    structured_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    application: Mapped["LoanApplication"] = relationship(
        back_populates="extracted_tables"
    )
    document: Mapped["Document"] = relationship(back_populates="extracted_tables")
    content: Mapped["DocumentContent | None"] = relationship(
        back_populates="extracted_tables"
    )
    financial_values: Mapped[list["FinancialValue"]] = relationship(
        back_populates="table",
        cascade="all, delete-orphan",
    )
