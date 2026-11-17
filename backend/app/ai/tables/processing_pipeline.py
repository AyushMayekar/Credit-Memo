from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from scripts.layout_table_reconstructor import reconstruct_table, markdown_table


class TableProcessingError(Exception):
    pass


class TableProcessingPipeline:
    """Reconstruct every plausible financial region from raw Docling items.

    Low-confidence regions are still attempted. A weak boundary score is not a
    reason to delete financial values; the reconstructed table is simply marked
    for review. Regions that cannot form stable numeric columns are recorded as
    failures so their source text remains available to the section parser.
    """

    VERSION = "deterministic-table-processing-v2"
    INCLUDED_REGIONS = {"HIGH_CONFIDENCE", "REVIEW_REQUIRED", "LOW_CONFIDENCE"}

    def run(self, *, extraction: dict[str, Any], regions: dict[str, Any]) -> dict[str, Any]:
        pages = {int(p["page_number"]): p for p in extraction.get("pages", [])}
        tables: list[dict[str, Any]] = []
        owned_ids: set[str] = set()
        failures: list[dict[str, Any]] = []

        for region in regions.get("regions", []):
            if region.get("classification") not in self.INCLUDED_REGIONS:
                continue
            page_no = int(region["page_number"])
            page = pages.get(page_no)
            if page is None:
                failures.append({"region_id": region.get("region_id"), "reason": "page_missing"})
                continue
            ids = {str(x) for x in region.get("source_item_ids", []) if x}
            selected = [x for x in page.get("items", []) if str(x.get("item_id")) in ids]
            if not selected:
                failures.append({"region_id": region.get("region_id"), "reason": "no_source_items"})
                continue
            try:
                table = reconstruct_table(selected)
                markdown = markdown_table(table)
            except Exception as exc:
                failures.append({"region_id": region.get("region_id"), "reason": str(exc)})
                continue

            audit = table.get("numeric_audit") or {}
            region_warnings = list(region.get("warnings") or [])
            review_reasons = list(table.get("warnings") or []) + region_warnings
            quality = (
                "ACCEPTED"
                if region.get("classification") == "HIGH_CONFIDENCE"
                and not table.get("warnings")
                and not region_warnings
                and audit.get("reconciled", False)
                and audit.get("data_row_count", 0) > 0
                else "REVIEW_REQUIRED"
            )
            table_id = f"P{page_no:04d}-T{len(tables) + 1:03d}"
            table.update(
                {
                    "table_id": table_id,
                    "page_number": page_no,
                    "table_type": "financial_table",
                    "source_region_id": region.get("region_id"),
                    "source_item_ids": [str(x.get("item_id")) for x in selected],
                    "source_bbox": region.get("bbox"),
                    "reading_order_start": region.get("reading_order_start"),
                    "reading_order_end": region.get("reading_order_end"),
                    "region_classification": region.get("classification"),
                    "region_confidence": region.get("confidence"),
                    "region_features": region.get("features"),
                    "region_warnings": region_warnings,
                    "quality_classification": quality,
                    "review_reasons": list(dict.fromkeys(review_reasons)),
                    "markdown": markdown,
                    "source_reference": f"page {page_no}, table {table_id}",
                }
            )
            tables.append(table)
            owned_ids.update(table["source_item_ids"])

        return {
            "pipeline_version": self.VERSION,
            "tables": tables,
            "table_owned_item_ids": sorted(owned_ids),
            "failures": failures,
        }
