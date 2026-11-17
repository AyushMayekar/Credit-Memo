from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING, Any
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
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
    from app.db.models.user import User


class CreditMemo(Base):
    __tablename__ = "credit_memos"
    __table_args__ = (UniqueConstraint("application_id", "version_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.loan_applications.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    memo_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="DRAFT"
    )
    memo_content: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        JSONB, nullable=False
    )
    schema_version: Mapped[str | None] = mapped_column(String(30))
    raw_generation_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    generated_html_path: Mapped[str | None] = mapped_column(Text)
    generated_pdf_path: Mapped[str | None] = mapped_column(Text)
    generated_by_model: Mapped[str | None] = mapped_column(String(150))
    prompt_version: Mapped[str | None] = mapped_column(String(80))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("credit_ai.users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    application: Mapped["LoanApplication"] = relationship(back_populates="credit_memos")
    reviewer: Mapped["User|None"] = relationship(back_populates="reviewed_memos")
