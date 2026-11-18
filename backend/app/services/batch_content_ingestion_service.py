from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.ai.chunking.pipeline import HybridTextChunkingPipeline
from app.ai.embedding_model import get_embedding_client
from app.ai.vectorstore.faiss_manager import FaissIndexManager
from app.core.config import settings
from app.db.models import (
    Document,
    DocumentContent,
    ExtractedTable,
    FaissIndex,
    FaissVectorMapping,
    LoanApplication,
)


@dataclass(frozen=True, slots=True)
class BatchIngestionResult:
    application_reference: str
    document_count: int
    parent_count: int
    text_count: int
    table_count: int
    vector_count: int
    embedding_request_count: int
    chunking_audit: list[dict[str, Any]]
    index_path: str
    status: str


class BatchContentIngestionService:
    """Persist chunker output and index only CHILD_CHUNK and TABLE_DATA.

    Parent sections are stored in PostgreSQL and are fetched through
    DocumentContent.parent_content_id. They are not embedded.
    """

    VECTOR_TYPES = {"CHILD_CHUNK", "TABLE_DATA"}

    def __init__(
        self,
        session: Session,
        *,
        embedder: Any | None = None,
        manager_factory: Callable[..., FaissIndexManager] = FaissIndexManager,
    ) -> None:
        self.session = session
        self.embedder = embedder or get_embedding_client()
        self.manager_factory = manager_factory

    def ingest_application(
        self,
        *,
        application_reference: str,
        document_ids: list[int],
        reporting_year: str | None = None,
        replace_existing: bool = True,
    ) -> BatchIngestionResult:
        application = self.session.scalar(
            select(LoanApplication).where(
                LoanApplication.application_reference == application_reference
            )
        )
        if application is None:
            raise ValueError("Application not found")
        unique_ids = list(dict.fromkeys(int(x) for x in document_ids))
        documents = list(
            self.session.scalars(
                select(Document)
                .where(Document.application_id == application.id, Document.id.in_(unique_ids))
                .order_by(Document.id)
            )
        )
        if len(documents) != len(unique_ids):
            raise ValueError("One or more documents do not belong to this application")
        if any(not document.parsed_document_path for document in documents):
            raise ValueError("Every document must have parsed_document_path before ingestion")

        index_path = settings.resolve_path(settings.faiss_dir) / f"{settings.faiss_index_name}.faiss"
        dimension = self._embedding_dimension()
        manager = self.manager_factory(index_path, dimension)
        backup = manager.create_backup()

        parent_total = child_total = table_total = request_total = 0
        audits: list[dict[str, Any]] = []
        vector_ids: list[int] = []
        vector_texts: list[str] = []
        vector_contents: list[DocumentContent] = []

        try:
            if replace_existing:
                old_vectors = list(
                    self.session.scalars(
                        select(FaissVectorMapping.faiss_vector_id).where(
                            FaissVectorMapping.document_id.in_(unique_ids),
                            FaissVectorMapping.is_active.is_(True),
                        )
                    )
                )
                manager.remove([int(x) for x in old_vectors])
                self.session.execute(delete(FaissVectorMapping).where(FaissVectorMapping.document_id.in_(unique_ids)))
                self.session.execute(delete(ExtractedTable).where(ExtractedTable.document_id.in_(unique_ids)))
                self.session.execute(delete(DocumentContent).where(DocumentContent.document_id.in_(unique_ids)))
                self.session.flush()

            next_vector_id = self._next_vector_id()
            chunker = HybridTextChunkingPipeline()

            for document in documents:
                result = chunker.run(
                    Path(document.parsed_document_path),
                    borrower_name=application.borrower.legal_name,
                    document_name=document.original_filename,
                    reporting_year=reporting_year,
                    document_id=document.id,
                )
                audits.append({"document_id": document.id, **result.audit})
                if result.audit["missing_record_ids"] or result.audit["missing_table_ids"]:
                    raise ValueError(
                        f"Chunking lost source content for document {document.id}: {result.audit}"
                    )

                parent_db: dict[str, DocumentContent] = {}
                for order, parent in enumerate(result.parents):
                    rec = DocumentContent(
                        application_id=application.id,
                        document_id=document.id,
                        content_type="PARENT_SECTION",
                        page_number=parent.page_start,
                        page_end=parent.page_end,
                        chunk_order=order,
                        chunk_index=order,
                        section_title=parent.section_title,
                        content_text=parent.content_text,
                        embedding_text=None,
                        search_summary=self._related_parent_preview(parent),
                        token_count=parent.token_count,
                        chunking_strategy=chunker.VERSION,
                        content_metadata={
                            **parent.metadata,
                            "chunk_id": parent.chunk_id,
                        },
                        reporting_year=reporting_year,
                        source_reference=(
                            f"{document.original_filename}, pages {parent.page_start}-{parent.page_end}, "
                            f"section {parent.section_title}, parent {parent.chunk_id}"
                        ),
                    )
                    self.session.add(rec)
                    self.session.flush()
                    parent_db[parent.chunk_id] = rec
                parent_total += len(result.parents)

                for order, child in enumerate(result.children):
                    parent = parent_db[child.parent_chunk_id]
                    rec = DocumentContent(
                        application_id=application.id,
                        document_id=document.id,
                        parent_content_id=parent.id,
                        content_type="CHILD_CHUNK",
                        page_number=child.page_start,
                        page_end=child.page_end,
                        chunk_order=order,
                        chunk_index=order,
                        section_title=child.section_title,
                        content_text=child.content_text,
                        embedding_text=child.embedding_text,
                        search_summary=None,
                        token_count=child.token_count,
                        chunking_strategy=chunker.VERSION,
                        content_metadata={
                            **child.metadata,
                            "chunk_id": child.chunk_id,
                        },
                        reporting_year=reporting_year,
                        source_reference=(
                            f"{document.original_filename}, pages {child.page_start}-{child.page_end}, "
                            f"section {child.section_title}, child {child.chunk_id}"
                        ),
                    )
                    self.session.add(rec)
                    self.session.flush()
                    vector_ids.append(next_vector_id)
                    next_vector_id += 1
                    vector_texts.append(child.embedding_text)
                    vector_contents.append(rec)
                child_total += len(result.children)

                source_tables = {
                    str(x.get("table_id")): x
                    for x in self._read_json(Path(document.parsed_document_path)).get("tables", [])
                }
                for order, table in enumerate(result.tables):
                    parent = parent_db[table.parent_chunk_id]
                    rec = DocumentContent(
                        application_id=application.id,
                        document_id=document.id,
                        parent_content_id=parent.id,
                        content_type="TABLE_DATA",
                        page_number=table.page_start,
                        page_end=table.page_end,
                        chunk_order=order,
                        chunk_index=order,
                        section_title=table.section_title,
                        content_text=table.content_text,
                        embedding_text=table.embedding_text,
                        search_summary=None,
                        token_count=table.token_count,
                        chunking_strategy=chunker.VERSION,
                        content_metadata={
                            **table.metadata,
                            "chunk_id": table.chunk_id,
                        },
                        reporting_year=reporting_year,
                        source_reference=(
                            f"{document.original_filename}, page {table.page_start}, "
                            f"table {table.table_id}, part {table.table_part_index}"
                        ),
                    )
                    self.session.add(rec)
                    self.session.flush()
                    source = source_tables.get(table.table_id, {})
                    extracted = ExtractedTable(
                        application_id=application.id,
                        document_id=document.id,
                        content_id=rec.id,
                        table_reference=table.chunk_id,
                        page_number=table.page_start,
                        section_id=table.section_id,
                        section_title=table.section_title,
                        bounding_box=source.get("source_bbox"),
                        original_rows=source.get("raw_rows") or [],
                        normalized_rows=source.get("normalized_rows") or [],
                        table_markdown=table.content_text,
                        reporting_periods=table.metadata.get("detected_periods") or [],
                        units=table.metadata.get("detected_units") or [],
                        uncertainties=table.metadata.get("warnings") or [],
                        quality_classification=table.quality_classification,
                        review_required=table.quality_classification == "REVIEW_REQUIRED",
                        context_status="CHUNKED",
                        structured_data=table.metadata,
                    )
                    self.session.add(extracted)
                    vector_ids.append(next_vector_id)
                    next_vector_id += 1
                    vector_texts.append(table.embedding_text)
                    vector_contents.append(rec)
                table_total += len(result.tables)

            embeddings, request_total = self._embed_many(vector_texts)
            manager.add_many(vector_ids, embeddings)
            manager.save_atomic()

            for vector_id, content in zip(vector_ids, vector_contents):
                self.session.add(
                    FaissVectorMapping(
                        faiss_vector_id=vector_id,
                        application_id=application.id,
                        document_id=content.document_id,
                        content_id=content.id,
                        index_name=settings.faiss_index_name,
                        embedding_model=settings.embedding_model,
                        embedding_dimension=dimension,
                        content_type=content.content_type,
                        is_active=True,
                    )
                )

            index_row = self.session.scalar(
                select(FaissIndex).where(FaissIndex.index_name == settings.faiss_index_name)
            )
            if index_row is None:
                index_row = FaissIndex(
                    index_name=settings.faiss_index_name,
                    index_path=str(index_path),
                    embedding_model=settings.embedding_model,
                    embedding_dimension=dimension,
                    distance_metric="COSINE",
                    total_vectors=manager.total_vectors,
                    index_status="ACTIVE",
                )
                self.session.add(index_row)
            else:
                index_row.index_path = str(index_path)
                index_row.embedding_model = settings.embedding_model
                index_row.embedding_dimension = dimension
                index_row.total_vectors = manager.total_vectors
                index_row.index_status = "ACTIVE"

            self.session.commit()
            manager.discard_backup(backup)
        except Exception:
            self.session.rollback()
            manager.restore_backup(backup)
            raise

        return BatchIngestionResult(
            application_reference=application_reference,
            document_count=len(documents),
            parent_count=parent_total,
            text_count=child_total,
            table_count=table_total,
            vector_count=len(vector_ids),
            embedding_request_count=request_total,
            chunking_audit=audits,
            index_path=str(index_path),
            status="COMPLETED",
        )

    def _embedding_dimension(self) -> int:
        for name in ("dimension", "embedding_dimension"):
            value = getattr(self.embedder, name, None)
            if isinstance(value, int) and value > 0:
                return value
        probe = self.embedder.embed_text("embedding dimension probe")
        return len(probe)

    def _embed_many(self, texts: list[str]) -> tuple[list[list[float]], int]:
        if not texts:
            return [], 0
        if hasattr(self.embedder, "embed_texts"):
            values = self.embedder.embed_texts(texts)
            return list(values), 1
        if hasattr(self.embedder, "embed_many"):
            values = self.embedder.embed_many(texts)
            return list(values), 1
        # Compatible fallback. Existing EmbeddingClient still applies its own
        # request validation when embed_text is called.
        return [self.embedder.embed_text(text) for text in texts], len(texts)

    def _next_vector_id(self) -> int:
        value = self.session.scalar(select(func.max(FaissVectorMapping.faiss_vector_id)))
        return int(value or 0) + 1

    @staticmethod
    def _related_parent_preview(parent) -> str:
        path = " > ".join(parent.heading_path)
        return (
            f"{path}; pages {parent.page_start}-{parent.page_end}; "
            f"part {parent.parent_part_index} of {parent.parent_part_count}"
        )[:500]

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
