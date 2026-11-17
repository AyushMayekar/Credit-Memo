from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.data_mismatch import DataMismatch
    from app.db.models.document import Document
    from app.db.models.extracted_table import ExtractedTable
    from app.db.models.loan_application import LoanApplication
    from app.db.models.user import User


class FinancialValue(Base):
    __tablename__ = "financial_values"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.loan_applications.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("credit_ai.documents.id", ondelete="SET NULL")
    )
    table_id: Mapped[int | None] = mapped_column(
        ForeignKey("credit_ai.extracted_tables.id", ondelete="SET NULL")
    )
    metric_name: Mapped[str] = mapped_column(String(150), nullable=False)
    metric_code: Mapped[str] = mapped_column(String(100), nullable=False)
    financial_year: Mapped[str] = mapped_column(String(20), nullable=False)
    extracted_value: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str | None] = mapped_column(String(10))
    page_number: Mapped[int | None] = mapped_column(Integer)
    source_text: Mapped[str | None] = mapped_column(Text)
    extraction_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    verification_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PENDING"
    )
    verified_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("credit_ai.users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    application: Mapped["LoanApplication"] = relationship(
        back_populates="financial_values"
    )
    document: Mapped["Document | None"] = relationship(
        back_populates="financial_values"
    )
    table: Mapped["ExtractedTable | None"] = relationship(
        back_populates="financial_values"
    )
    verifier: Mapped["User | None"] = relationship(
        back_populates="verified_financial_values"
    )
    first_mismatches: Mapped[list["DataMismatch"]] = relationship(
        back_populates="first_value", foreign_keys="DataMismatch.first_value_id"
    )
    second_mismatches: Mapped[list["DataMismatch"]] = relationship(
        back_populates="second_value", foreign_keys="DataMismatch.second_value_id"
    )
    accepted_mismatches: Mapped[list["DataMismatch"]] = relationship(
        back_populates="accepted_value", foreign_keys="DataMismatch.accepted_value_id"
    )
