from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_PAGES = [
    2, 3, 10, 13, 32, 41, 43, 50,
    54, 55, 57, 65, 98, 99
]

SYMBOL_HEADING_RE = re.compile(r"[!@#=<>]{2,}")
PERSON_RE = re.compile(
    r"^(?:[A-Z]\.?\s+){1,4}[A-Z][A-Za-z'-]+$"
)

SUSPICIOUS_TITLES = {
    "goodwin plc",
    "directors:",
    "auditor:",
    "notes:",
    "document",
}


def clip(value: Any, limit: int = 350) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parsed", required=True, type=Path)
    parser.add_argument(
        "--output",
        default=Path("parsed_output_review.json"),
        type=Path,
    )
    parser.add_argument(
        "--pages",
        nargs="*",
        type=int,
        default=DEFAULT_PAGES,
    )
    parser.add_argument(
        "--preview-length",
        type=int,
        default=350,
    )
    args = parser.parse_args()

    parsed = json.loads(
        args.parsed.read_text(encoding="utf-8")
    )

    wanted_pages = set(args.pages)

    sections = parsed.get("sections") or []
    records = parsed.get("records") or []
    tables = parsed.get("tables") or []
    decisions = parsed.get("item_decisions") or []
    pages = parsed.get("pages") or []

    section_map = {
        section.get("section_id"): section
        for section in sections
    }

    suspicious_sections = []

    for section in sections:
        title = str(section.get("title") or "").strip()
        lowered = title.casefold()
        reasons = []

        if lowered in SUSPICIOUS_TITLES:
            reasons.append("generic_or_label_title")

        if PERSON_RE.fullmatch(title):
            reasons.append("possible_person_name")

        if SYMBOL_HEADING_RE.search(title):
            reasons.append("symbol_heavy_title")

        if "(continued)" in lowered:
            reasons.append("continued_remains_in_title")

        if len(title.split()) > 18:
            reasons.append("very_long_heading")

        if title.endswith(":"):
            reasons.append("label_like_heading")

        if reasons:
            suspicious_sections.append(
                {
                    "section_id": section.get("section_id"),
                    "title": title,
                    "heading_level": section.get("heading_level"),
                    "parent_section_id": section.get(
                        "parent_section_id"
                    ),
                    "page_start": section.get("page_start"),
                    "page_end": section.get("page_end"),
                    "reasons": reasons,
                }
            )

    selected_pages = []

    for page_number in sorted(wanted_pages):
        page_summary = next(
            (
                page
                for page in pages
                if int(page.get("page_number") or 0)
                == page_number
            ),
            None,
        )

        page_records = [
            record
            for record in records
            if int(record.get("page_start") or 0)
            <= page_number
            <= int(record.get("page_end") or 0)
        ]

        page_tables = [
            table
            for table in tables
            if int(table.get("page_number") or 0)
            == page_number
        ]

        page_decisions = [
            decision
            for decision in decisions
            if int(decision.get("page_number") or 0)
            == page_number
        ]

        decision_counts = Counter(
            decision.get("decision")
            for decision in page_decisions
        )

        decision_samples = {}

        for decision_type in (
            "KEEP",
            "REPLACED_BY_TABLE",
            "REJECTED_GARBAGE",
            "PAGE_FURNITURE",
        ):
            decision_samples[decision_type] = [
                {
                    "item_id": decision.get("item_id"),
                    "quality": decision.get("quality"),
                    "matched_table_id": decision.get(
                        "matched_table_id"
                    ),
                    "reasons": decision.get("reasons"),
                }
                for decision in page_decisions
                if decision.get("decision") == decision_type
            ][:15]

        selected_pages.append(
            {
                "page_number": page_number,
                "page_summary": page_summary,
                "decision_counts": dict(decision_counts),
                "decision_samples": decision_samples,
                "records": [
                    {
                        "record_id": record.get("record_id"),
                        "record_type": record.get("record_type"),
                        "section_id": record.get("section_id"),
                        "section_title": record.get(
                            "section_title"
                        ),
                        "quality_classification": record.get(
                            "quality_classification"
                        ),
                        "source_item_ids": (
                            record.get("source_item_ids") or []
                        )[:30],
                        "content_preview": clip(
                            record.get("content_text"),
                            args.preview_length,
                        ),
                    }
                    for record in page_records
                ],
                "tables": [
                    {
                        "table_id": table.get("table_id"),
                        "title": table.get("title"),
                        "section_id": table.get("section_id"),
                        "section_title": table.get(
                            "section_title"
                        ),
                        "quality_classification": table.get(
                            "quality_classification"
                        ),
                        "source_bbox": table.get("source_bbox"),
                        "warnings": table.get("warnings"),
                        "row_count": table.get("row_count"),
                        "sample_rows": (
                            table.get("normalized_rows") or []
                        )[:5],
                        "native_line_samples": (
                            table.get("native_lines") or []
                        )[:5],
                    }
                    for table in page_tables
                ],
            }
        )

    replaced_by_page = Counter(
        int(decision.get("page_number") or 0)
        for decision in decisions
        if decision.get("decision")
        == "REPLACED_BY_TABLE"
    )

    garbage_by_page = Counter(
        int(decision.get("page_number") or 0)
        for decision in decisions
        if decision.get("decision")
        == "REJECTED_GARBAGE"
    )

    record_types = Counter(
        record.get("record_type")
        for record in records
    )

    report = {
        "parser_version": parsed.get("parser_version"),
        "document": parsed.get("document"),
        "summary": {
            "section_count": len(sections),
            "record_count": len(records),
            "table_count": len(tables),
            "item_decision_count": len(decisions),
            "record_types": dict(record_types),
            "suspicious_section_count": len(
                suspicious_sections
            ),
        },
        "highest_table_replacement_pages": [
            {
                "page_number": page_number,
                "replaced_item_count": count,
            }
            for page_number, count
            in replaced_by_page.most_common(15)
        ],
        "highest_garbage_pages": [
            {
                "page_number": page_number,
                "garbage_item_count": count,
            }
            for page_number, count
            in garbage_by_page.most_common(15)
        ],
        "suspicious_sections": suspicious_sections[:100],
        "selected_pages": selected_pages,
    }

    args.output.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "status": "PARSED_OUTPUT_REVIEW_CREATED",
                "output": str(args.output.resolve()),
                "selected_pages": sorted(wanted_pages),
                "suspicious_sections": len(
                    suspicious_sections
                ),
                "record_types": dict(record_types),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()