from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.document import Document
    from app.db.models.document_content import DocumentContent
    from app.db.models.loan_application import LoanApplication


class FaissVectorMapping(Base):
    __tablename__ = "faiss_vector_mappings"
    __table_args__ = (UniqueConstraint("content_id", "index_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    faiss_vector_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, unique=True
    )
    application_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.loan_applications.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.documents.id", ondelete="CASCADE"), nullable=False
    )
    content_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ai.document_contents.id", ondelete="CASCADE"), nullable=False
    )
    index_name: Mapped[str] = mapped_column(String(150), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(30), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    application: Mapped["LoanApplication"] = relationship(
        back_populates="faiss_vector_mappings"
    )
    document: Mapped["Document"] = relationship(back_populates="faiss_vector_mappings")
    content: Mapped["DocumentContent"] = relationship(back_populates="faiss_mappings")
