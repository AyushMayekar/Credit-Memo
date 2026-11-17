from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.loan_application import LoanApplication
    from app.db.models.user import User


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("credit_ai.loan_applications.id", ondelete="SET NULL")
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("credit_ai.users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(150), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(100))
    entity_id: Mapped[int | None]
    old_value: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB)
    new_value: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    application: Mapped["LoanApplication | None"] = relationship(
        back_populates="audit_logs"
    )
    user: Mapped["User | None"] = relationship(back_populates="audit_logs")
