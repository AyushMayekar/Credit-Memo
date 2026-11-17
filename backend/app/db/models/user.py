from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.audit_log import AuditLog
    from app.db.models.credit_memo import CreditMemo
    from app.db.models.data_mismatch import DataMismatch
    from app.db.models.financial_value import FinancialValue
    from app.db.models.loan_application import LoanApplication


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="CREDIT_ANALYST"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    loan_applications: Mapped[list["LoanApplication"]] = relationship(
        back_populates="creator"
    )
    verified_financial_values: Mapped[list["FinancialValue"]] = relationship(
        back_populates="verifier"
    )
    resolved_mismatches: Mapped[list["DataMismatch"]] = relationship(
        back_populates="resolver"
    )
    reviewed_memos: Mapped[list["CreditMemo"]] = relationship(back_populates="reviewer")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")
