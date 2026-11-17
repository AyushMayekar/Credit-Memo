from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.credit_policy_rule import CreditPolicyRule
    from app.db.models.loan_application import LoanApplication


class RiskFlag(Base):
    __tablename__ = "risk_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.loan_applications.id", ondelete="CASCADE"), nullable=False
    )
    policy_rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("credit_ai.credit_policy_rules.id", ondelete="SET NULL")
    )
    risk_category: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_title: Mapped[str] = mapped_column(String(250), nullable=False)
    risk_description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB)
    mitigation: Mapped[str | None] = mapped_column(Text)
    analyst_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="OPEN"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    application: Mapped["LoanApplication"] = relationship(back_populates="risk_flags")
    policy_rule: Mapped["CreditPolicyRule | None"] = relationship(
        back_populates="risk_flags"
    )
