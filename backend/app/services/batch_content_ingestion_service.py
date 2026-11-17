from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import (
    Document,
    DocumentContent,
    ExtractedTable,
    LoanApplication,
)
from app.services.job_service import JobService
from app.services.content_review_service import ContentReviewService


# ------------------------------------------------------------------ #
#  Ingestion entry‑point
# ------------------------------------------------------------------ #
def ingest_parsed_document(
    session: Session,
    *,
    application_id: int,
    document_id: int,
    parsed_path: Path,
    job_ref: str | None = None,
) -> Dict[str, Any]:
    """
    Run the hierarchical chunker on a previously parsed document and
    persist the resulting parent/child chunks and table chunks into the
    database.

    Returns a dict with basic statistics that can be posted back to the
    orchestration job.
    """
    # ------------------------------------------------------------------
    #  1️⃣  Load the parsed document and run the chunker
    # ------------------------------------------------------------------
    from app.ai.chunking.pipeline import run as chunker_run

    chunk_result = chunker_run(parsed_path)
    parents = chunk_result["parents"]
    children = chunk_result["children"]
    tables = chunk_result["tables"]
    audit = chunk_result["audit"]

    # ------------------------------------------------------------------
    #  2️⃣  Persist Parent (section) chunks as DocumentContent rows
    # ------------------------------------------------------------------
    parent_records: List[DocumentContent] = []

    for p in parents:
        rec = DocumentContent(
            application_id=application_id,
            document_id=document_id,
            content_type="PARENT_SECTION",
            page_number=p["page_start"],
            page_end=p["page_end"],
            chunk_order=len(parent_records),
            chunk_index=p["chunk_id"],
            content_text=p["title"],                     # short title used as preview
            quality_classification=p.get("quality_classification"),
            search_priority=p.get("search_priority", "HIGH"),
            metadata=json.dumps(
                {
                    "heading_level": p.get("heading_level"),
                    "heading_path": p.get("heading_path"),
                    "record_ids": p.get("record_ids"),
                    "chunk_version": p.get("chunk_version"),
                }
            ),
        )
        parent_records.append(rec)

    session.add_all(parent_records)
    session.flush()  # obtain IDs

    # ------------------------------------------------------------------
    #  3️⃣  Persist Child (narrative) chunks
    # ------------------------------------------------------------------
    child_records: List[DocumentContent] = []

    for c in children:
        rec = DocumentContent(
            application_id=application_id,
            document_id=document_id,
            content_type="SECTION_TEXT",
            page_number=c["page_start"],
            page_end=c["page_end"],
            chunk_order=len(child_records) + len(parent_records),
            chunk_index=c["chunk_id"],
            content_text=c["content_text"],
            quality_classification=c.get("quality_classification"),
            search_priority=c.get("search_priority", "HIGH"),
            metadata=json.dumps(
                {
                    "parent_chunk_id": c["parent_chunk_id"],
                    "heading_path": next(
                        (s.get("heading_path") for s in parents
                         if s["chunk_id"] == c["parent_chunk_id"]), []
                    ),
                    "chunk_version": c.get("chunk_version"),
                }
            ),
        )
        child_records.append(rec)

    session.add_all(child_records)
    session.flush()

    # ------------------------------------------------------------------
    #  4️⃣  Persist Table chunks as ExtractedTable rows
    # ------------------------------------------------------------------
    table_records: List[ExtractedTable] = []

    for t in tables:
        # Derive a unique reference; we use the table_id.
        table_ref = t["chunk_id"]  # e.g. "P0065-T001"
        page = t["page_start"]

        md = t.get("content_text") or ""

        rec = ExtractedTable(
            application_id=application_id,
            document_id=document_id,
            table_reference=table_ref,
            page_number=page,
            section_id=t.get("parent_chunk_id", None),
            section_title=t.get("title") or "",
            bounding_box=json.loads(
                t.get("metadata", "{}").get("bbox") or "[]"
            ),
            original_rows=json.loads(
                json.dumps(t.get("metadata", {}).get("raw_rows") or [])
            ),
            normalized_rows=json.loads(
                json.dumps(t.get("metadata", {}).get("normalized_rows") or [])
            ),
            table_markdown=md,
            reporting_periods=json.loads(
                json.dumps(t.get("metadata", {}).get("detected_periods") or [])
            ),
            units=json.loads(
                json.dumps(t.get("metadata", {}).get("detected_units") or [])
            ),
            important_facts=[],
            financial_topics=[],
            uncertainties=json.loads(
                json.dumps(t.get("metadata", {}).get("warnings") or [])
            ),
            quality_classification=t.get("quality_classification"),
            review_required=t.get("quality_classification") == "REVIEW_REQUIRED",
            context_status="DETERMINISTIC_READY",
            structured_data=json.loads(
                json.dumps(t.get("metadata", {}))
            ),
        )
        table_records.append(rec)

    session.add_all(table_records)
    session.flush()

    # ------------------------------------------------------------------
    #  5️⃣  Optionally run the ContentReviewService to surface tables
    # ------------------------------------------------------------------
    # (Only if the job wants a human‑in‑the‑loop review step.)
    # reviewSvc = ContentReviewService(session)
    # reviewSvc.create_from_structure(application_id, document)

    # ------------------------------------------------------------------
    #  6️⃣  Return audit statistics
    # ------------------------------------------------------------------
    return {
        "parent_chunk_count": len(parent_records),
        "child_chunk_count": len(child_records),
        "table_chunk_count": len(table_records),
        "audit": audit,
        "status": "COMPLETED",
    }