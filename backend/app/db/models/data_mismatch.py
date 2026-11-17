from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.financial_value import FinancialValue
    from app.db.models.loan_application import LoanApplication
    from app.db.models.user import User


class DataMismatch(Base):
    __tablename__ = "data_mismatches"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.loan_applications.id", ondelete="CASCADE"), nullable=False
    )
    metric_code: Mapped[str] = mapped_column(String(100), nullable=False)
    financial_year: Mapped[str] = mapped_column(String(20), nullable=False)
    first_value_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.financial_values.id"), nullable=False
    )
    second_value_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.financial_values.id"), nullable=False
    )
    difference_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    difference_percent: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    materiality: Mapped[str] = mapped_column(String(30), nullable=False)
    resolution_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="UNRESOLVED"
    )
    accepted_value_id: Mapped[int | None] = mapped_column(
        ForeignKey("credit_ai.financial_values.id")
    )
    analyst_justification: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("credit_ai.users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    application: Mapped["LoanApplication"] = relationship(
        back_populates="data_mismatches", foreign_keys=[application_id]
    )
    first_value: Mapped["FinancialValue"] = relationship(
        back_populates="first_mismatches", foreign_keys=[first_value_id]
    )
    second_value: Mapped["FinancialValue"] = relationship(
        back_populates="second_mismatches", foreign_keys=[second_value_id]
    )
    accepted_value: Mapped["FinancialValue | None"] = relationship(
        back_populates="accepted_mismatches", foreign_keys=[accepted_value_id]
    )
    resolver: Mapped["User | None"] = relationship(back_populates="resolved_mismatches")
