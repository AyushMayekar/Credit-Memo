from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.audit_log import AuditLog
    from app.db.models.borrower import Borrower
    from app.db.models.calculated_metric import CalculatedMetric
    from app.db.models.credit_memo import CreditMemo
    from app.db.models.data_mismatch import DataMismatch
    from app.db.models.document import Document
    from app.db.models.document_content import DocumentContent
    from app.db.models.extracted_image import ExtractedImage
    from app.db.models.extracted_table import ExtractedTable
    from app.db.models.faiss_vector_mapping import FaissVectorMapping
    from app.db.models.financial_value import FinancialValue
    from app.db.models.risk_flag import RiskFlag
    from app.db.models.user import User


class LoanApplication(Base):
    __tablename__ = "loan_applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_reference: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True
    )
    borrower_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.borrowers.id"), nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("credit_ai.users.id"))
    loan_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    loan_purpose: Mapped[str] = mapped_column(Text, nullable=False)
    tenure_months: Mapped[int] = mapped_column(Integer, nullable=False)
    proposed_interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    repayment_frequency: Mapped[str | None] = mapped_column(String(30))
    collateral_description: Mapped[str | None] = mapped_column(Text)
    existing_obligations: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    borrower: Mapped["Borrower"] = relationship(back_populates="loan_applications")
    creator: Mapped["User | None"] = relationship(back_populates="loan_applications")
    documents: Mapped[list["Document"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    document_contents: Mapped[list["DocumentContent"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    faiss_vector_mappings: Mapped[list["FaissVectorMapping"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    extracted_tables: Mapped[list["ExtractedTable"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    extracted_images: Mapped[list["ExtractedImage"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    financial_values: Mapped[list["FinancialValue"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    calculated_metrics: Mapped[list["CalculatedMetric"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    data_mismatches: Mapped[list["DataMismatch"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        foreign_keys="DataMismatch.application_id",
    )
    risk_flags: Mapped[list["RiskFlag"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    credit_memos: Mapped[list["CreditMemo"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="application")
