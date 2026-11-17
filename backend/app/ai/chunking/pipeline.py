from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

from app.ai.parsing.models import StructuralParsingResult


# ------------------------------------------------------------------ #
#  Data containers (simple dicts – no ORM needed for the chunker)
# ------------------------------------------------------------------ #
ParentChunk = Dict[str, Any]        # one parent (section) chunk
ChildChunk  = Dict[str, Any]        # one narrative child chunk
TableChunk  = Dict[str, Any]        # one table chunk (excluded from text)


# ------------------------------------------------------------------ #
#  Helper: clean a string the same way the parser does
# ------------------------------------------------------------------ #
def _clean(text: Any) -> str:
    """collapse whitespace, strip None/empty."""
    if not text:
        return ""
    return " ".join(str(text).split())


# ------------------------------------------------------------------ #
#  Core chunking function
# ------------------------------------------------------------------ #
def run(
    structure_path: Path,
    *,
    borrower_name: str,
    document_name: str | None = None,
    reporting_year: str | None = None,
) -> Dict[str, Any]:
    """
    Parameters
    ----------
    structure_path : Path
        Path to the parsed_document.json produced by LightweightParsingPipelineV8.
    borrower_name : str
        Name used for metadata (often derived from the application).
    document_name : optional
        File name of the source PDF.
    reporting_year : optional
        Fiscal year string (e.g. "2024").

    Returns
    -------
    Dict with three keys:
        - "parents"   : list[ParentChunk]   – one entry per section.
        - "children"  : list[ChildChunk]    – one entry per SECTION_TEXT record.
        - "tables"    : list[TableChunk]    – one entry per financial table.
    """
    # ------------------------------------------------------------------
    #  Load the parsed document
    # ------------------------------------------------------------------
    payload = json.loads(structure_path.read_text(encoding="utf-8"))
    doc = payload.get("document") or {}
    sections: List[Dict[str, Any]] = payload.get("sections") or []
    records: List[Dict[str, Any]] = payload.get("records") or []
    tables: List[Dict[str, Any]] = payload.get("tables") or []
    pages: List[Dict[str, Any]] = payload.get("pages") or []

    # ------------------------------------------------------------------
    #  Index sections by id for quick parent‑link lookup
    # ------------------------------------------------------------------
    section_by_id: Dict[str, Dict[str, Any]] = {
        s["section_id"]: s for s in sections
    }

    # ------------------------------------------------------------------
    #  ------------------------------------------------------------------
    #  1️⃣  Parent chunks – one per section (heading hierarchy)
    # ------------------------------------------------------------------
    parents: List[ParentChunk] = []

    for sec in sections:
        sid = sec["section_id"]
        title = sec.get("title") or "Untitled"
        level = sec.get("heading_level") or 1
        page_start = sec.get("page_start") or 0
        page_end = sec.get("page_end") or 0
        heading_path = sec.get("heading_path") or [title]

        # collect child‑record ids that belong to this section
        child_record_ids: List[str] = [
            rid for rid in sec.get("record_ids", [])
        ]

        parent_chunk: ParentChunk = {
            "chunk_id": f"SEC-{sid}",
            "table_id": None,
            "page_start": page_start,
            "page_end": page_end,
            "title": title,
            "heading_level": level,
            "heading_path": heading_path,
            "record_ids": child_record_ids,
            "quality_classification": sec.get("quality_classification"),
            "search_priority": "HIGH",
            "chunk_version": "chunkers-v2.1",
        }
        parents.append(parent_chunk)

    # ------------------------------------------------------------------
    #  ------------------------------------------------------------------
    #  2️⃣  Child chunks – one per SECTION_TEXT record
    # ------------------------------------------------------------------
    children: List[ChildChunk] = []

    # group records by their section_id
    records_by_section: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for rec in records:
        records_by_section[rec.get("section_id", "")].append(rec)

    for sec in sections:
        sid = sec["section_id"]
        for rec in records_by_section.get(sid, []):
            rid = rec["record_id"]
            page_start = rec.get("page_start") or 0
            page_end = rec.get("page_end") or 0
            content_text = _clean(rec.get("content_text"))

            child: ChildChunk = {
                "chunk_id": rid,
                "parent_chunk_id": f"SEC-{sid}",
                "page_start": page_start,
                "page_end": page_end,
                "title": rec.get("section_title") or sec.get("title") or "",
                "content_text": content_text,
                "quality_classification": rec.get("quality_classification"),
                "search_priority": "HIGH",
                "chunk_version": "chunkers-v2.1",
            }
            children.append(child)

    # ------------------------------------------------------------------
    #  3️⃣  Table chunks – emitted but marked “excluded from text”
    # ------------------------------------------------------------------
    table_chunks: List[TableChunk] = []

    for tbl in tables:
        tid = tbl.get("table_id", f"TABLE-{tbl.get('page_number')}")
        page = tbl.get("page_number")
        section_title = tbl.get("section_title") or ""
        quality = tbl.get("quality_classification", "UNKNOWN")

        # Build a tiny markdown snippet from the table (already present)
        markdown = tbl.get("markdown") or ""

        table_chunk: TableChunk = {
            "chunk_id": tid,
            "table_id": tid,
            "page_start": page,
            "page_end": page,
            "title": section_title,
            "content_text": markdown,          # reuse the pre‑generated markdown
            "quality_classification": quality,
            "search_priority": "HIGH",
            "chunk_version": "chunkers-v2.1",
            "metadata": {
                "raw_rows": tbl.get("raw_rows") or [],
                "normalized_rows": tbl.get("normalized_rows") or [],
                "row_records": tbl.get("row_records") or [],
                "column_labels": tbl.get("column_labels") or [],
                "detected_periods": tbl.get("detected_periods") or [],
                "detected_units": tbl.get("detected_units") or [],
                "numeric_audit": tbl.get("numeric_audit") or {},
                "region_confidence": tbl.get("region_confidence"),
                "warnings": tbl.get("review_reasons") or tbl.get("warnings") or [],
                "source_reference": tbl.get("source_reference"),
            },
        }
        table_chunks.append(table_chunk)

    # ------------------------------------------------------------------
    #  4️⃣  Return a small result dict the ingestion service can consume
    # ------------------------------------------------------------------
    return {
        "parents": parents,
        "children": children,
        "tables": table_chunks,
        "audit": {
            "source_item_count": payload.get("audit", {}).get(
                "source_item_count", 0
            ),
            "table_owned_count": payload.get("audit", {}).get(
                "table_owned_count", 0
            ),
            "garbage_removed": payload.get("audit", {}).get(
                "garbage_removed", 0
            ),
            "duplicate_removed": payload.get("audit", {}).get(
                "duplicate_removed", 0
            ),
            "furniture_removed": payload.get("audit", {}).get(
                "furniture_removed", 0
            ),
            "section_count": len(parents),
            "table_count": len(table_chunks),
            "record_count": len(children),
        },
    }


# ------------------------------------------------------------------ #
#  CLI entry‑point (optional – useful for ad‑hoc runs)
# ------------------------------------------------------------------ #
def main(argv: List[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Hierarchical textual chunker for Docling‑v8 parsed docs."
    )
    parser.add_argument(
        "--extraction",
        required=True,
        type=Path,
        help="Path to the extraction.json (raw Docling output).",
    )
    parser.add_argument(
        "--parsed",
        required=True,
        type=Path,
        help="Path to parsed_document.json (output of LightweightParsingPipelineV8).",
    )
    parser.add_argument(
        "--borrower",
        required=True,
        help="Borrower / application name.",
    )
    parser.add_argument(
        "--document",
        default=None,
        help="Source PDF file name (optional).",
    )
    parser.add_argument(
        "--year",
        default=None,
        help="Reporting year (optional).",
    )
    parser.add_argument(
        "--output",
        default=Path("chunking-output.json"),
        type=Path,
        help="Where to write the chunking result JSON.",
    )

    args = parser.parse_args(argv)

    # First run the parser if only the raw extraction is available
    from app.ai.parsing.lightweight_parser_v8 import LightweightParsingPipelineV8
    from datetime import date

    if args.extraction.exists() and not args.parsed.exists():
        r = LightweightParsingPipelineV8(parsed_root=Path("storage/parsed-v8")).parse(
            extraction_path=args.extraction,
            table_regions_path=None,
            application_reference=args.borrower,
            document_reference=args.document or "DOC",
        )
        parsed_path = Path(r.parsed_document_path)
    else:
        parsed_path = args.parsed

    result = run(parsed_path, borrower_name=args.borrower,
                 document_name=args.document, reporting_year=args.year)

    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"✅ Chunking written to {args.output}")


if __name__ == "__main__":
    main()