from __future__ import annotations
from datetime import datetime
from typing import Any
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class ContentReviewItem(Base):
    __tablename__ = "content_review_items"
    __table_args__ = (UniqueConstraint("document_id", "item_type", "item_reference"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.loan_applications.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.documents.id", ondelete="CASCADE"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_reference: Mapped[str] = mapped_column(String(50), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    section_title: Mapped[str | None] = mapped_column(Text)
    preview_path: Mapped[str | None] = mapped_column(Text)
    source_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    quality_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="CONFIRMED"
    )
    selected_for_analysis: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    excluded_by_user: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
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
