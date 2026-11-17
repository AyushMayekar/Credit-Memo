from __future__ import annotations
from datetime import datetime
from typing import Any
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class RagGeneration(Base):
    __tablename__ = "rag_generations"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.loan_applications.id", ondelete="CASCADE"), nullable=False
    )
    request_type: Mapped[str] = mapped_column(String(30), nullable=False)
    route: Mapped[str] = mapped_column(String(30), nullable=False)
    user_query: Mapped[str | None] = mapped_column(Text)
    predefined_prompt_key: Mapped[str | None] = mapped_column(String(80))
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_snapshot: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="COMPLETED")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
