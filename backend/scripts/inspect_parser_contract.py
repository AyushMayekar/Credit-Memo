from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_PAGES = [10, 41, 43, 54, 65, 98]


def clip(value: Any, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def item_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": item.get("item_id"),
        "item_type": item.get("item_type"),
        "label": item.get("label"),
        "text": clip(item.get("text")),
        "reading_order": item.get("reading_order"),
        "bbox": item.get("bbox"),
    }


def table_summary(table: dict[str, Any]) -> dict[str, Any]:
    rows = table.get("rows") or []

    return {
        "table_id": table.get("table_id"),
        "title": clip(table.get("title")),
        "quality_classification": table.get("quality_classification"),
        "bbox_pdfplumber": table.get("bbox_pdfplumber"),
        "detected_periods": table.get("detected_periods"),
        "detected_units": table.get("detected_units"),
        "row_count": table.get("row_count"),
        "sample_rows": rows[:3],
        "sample_native_lines": [
            {
                "top": line.get("top"),
                "text": clip(line.get("text")),
            }
            for line in (table.get("native_lines") or [])[:3]
        ],
        "warnings": table.get("warnings") or [],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument(
        "--output",
        default=Path("parser_contract_report.json"),
        type=Path,
    )
    parser.add_argument(
        "--pages",
        nargs="*",
        type=int,
        default=DEFAULT_PAGES,
    )
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    wanted = set(args.pages)

    report: dict[str, Any] = {
        "schema_version": payload.get("schema_version"),
        "extraction_method": payload.get("extraction_method"),
        "document": {
            "filename": (payload.get("document") or {}).get("filename"),
            "source_page_count": (
                payload.get("document") or {}
            ).get("source_page_count"),
        },
        "pages": [],
    }

    for page in payload.get("pages") or []:
        page_number = int(page.get("page_number") or 0)
        if page_number not in wanted:
            continue

        items = page.get("items") or []
        tables = page.get("tables") or []

        headings = [
            item_summary(item)
            for item in items
            if item.get("item_type") == "heading"
        ][:8]

        body_items = [
            item_summary(item)
            for item in items
            if item.get("item_type") != "heading"
        ][:8]

        report["pages"].append(
            {
                "page_number": page_number,
                "width_points": page.get("width_points"),
                "height_points": page.get("height_points"),
                "item_count": len(items),
                "table_count": len(tables),
                "page_text_preview": clip(page.get("page_text"), 300),
                "heading_samples": headings,
                "body_samples": body_items,
                "table_samples": [
                    table_summary(table) for table in tables[:2]
                ],
            }
        )

    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "status": "PARSER_CONTRACT_REPORT_CREATED",
                "output": str(args.output.resolve()),
                "pages": [
                    page["page_number"] for page in report["pages"]
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()