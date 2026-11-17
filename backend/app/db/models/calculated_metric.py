from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.loan_application import LoanApplication


class CalculatedMetric(Base):
    __tablename__ = "calculated_metrics"
    __table_args__ = (
        UniqueConstraint("application_id", "metric_code", "financial_year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.loan_applications.id", ondelete="CASCADE"), nullable=False
    )
    metric_name: Mapped[str] = mapped_column(String(150), nullable=False)
    metric_code: Mapped[str] = mapped_column(String(100), nullable=False)
    financial_year: Mapped[str] = mapped_column(String(20), nullable=False)
    calculated_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    unit: Mapped[str | None] = mapped_column(String(50))
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    input_values: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        JSONB, nullable=False
    )
    source_financial_ids: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        JSONB
    )
    calculation_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="CALCULATED"
    )
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    application: Mapped["LoanApplication"] = relationship(
        back_populates="calculated_metrics"
    )
