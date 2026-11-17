from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.risk_flag import RiskFlag


class CreditPolicyRule(Base):
    __tablename__ = "credit_policy_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    rule_name: Mapped[str] = mapped_column(String(200), nullable=False)
    borrower_type: Mapped[str | None] = mapped_column(String(50))
    metric_code: Mapped[str] = mapped_column(String(100), nullable=False)
    operator: Mapped[str] = mapped_column(String(30), nullable=False)
    threshold_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    secondary_threshold: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    risk_severity: Mapped[str] = mapped_column(String(20), nullable=False)
    risk_category: Mapped[str] = mapped_column(String(100), nullable=False)
    message_template: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    risk_flags: Mapped[list["RiskFlag"]] = relationship(back_populates="policy_rule")
