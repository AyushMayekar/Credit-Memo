from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.ai.tables.normalizer import TableNormalizer


class ParsedTableBuilder:
    NUMBER_RE = re.compile(
        r"^\(?[-+]?\s*(?:£|\$|€|₹)?\s*\d[\d,]*(?:\.\d+)?\s*(?:%|p)?\)?$"
    )

    def __init__(self) -> None:
        self.normalizer = TableNormalizer()

    def parse(
        self,
        *,
        table: dict[str, Any],
        page: dict[str, Any],
    ) -> dict[str, Any]:
        raw_rows = table.get("rows") or []
        normalized = self.normalizer.normalize(raw_rows)
        rows = self._remove_empty_columns(normalized.normalized_rows)
        rows = self._remove_duplicate_rows(rows)
        row_records = [self._row_record(index, row) for index, row in enumerate(rows)]

        warnings = list(normalized.warnings)
        suspicious_rows = sum(
            record["quality"] == "REVIEW_REQUIRED" for record in row_records
        )
        garbage_rows = sum(record["quality"] == "REJECTED" for record in row_records)
        if suspicious_rows:
            warnings.append("contains_review_rows")
        if garbage_rows:
            warnings.append("contains_rejected_rows")

        accepted_rows = [
            record for record in row_records if record["quality"] != "REJECTED"
        ]
        classification = "ACCEPTED"
        if not accepted_rows or len(accepted_rows) < 2:
            classification = "REJECTED"
        elif suspicious_rows or page.get("quality_status") == "REVIEW_REQUIRED":
            classification = "REVIEW_REQUIRED"

        return {
            "table_id": table.get("table_id"),
            "page_number": page["page_number"],
            "section_id": page.get("section_id"),
            "section_title": page.get("section_title"),
            "source_strategy": table.get("extraction_strategy"),
            "source_bbox": table.get("bbox"),
            "raw_rows": raw_rows,
            "normalized_rows": [item["cells"] for item in accepted_rows],
            "row_records": row_records,
            "row_count": len(accepted_rows),
            "column_count": max(
                (len(item["cells"]) for item in accepted_rows), default=0
            ),
            "detected_periods": normalized.detected_periods,
            "detected_units": normalized.detected_units,
            "markdown": self.normalizer.to_markdown(
                [item["cells"] for item in accepted_rows]
            ),
            "quality_classification": classification,
            "warnings": sorted(set(warnings)),
            "source_reference": f"page {page['page_number']} table {table.get('table_id')}",
        }

    def _row_record(self, index: int, row: list[str]) -> dict[str, Any]:
        cells = [self.clean(cell) for cell in row]
        populated = [cell for cell in cells if cell]
        label = next(
            (cell for cell in populated if re.search(r"[A-Za-z]{2,}", cell)), ""
        )
        numbers = [self._number_value(cell) for cell in populated]
        parsed_numbers = [item for item in numbers if item is not None]
        symbol_ratio = sum(
            sum(char in "#*=<>@\\^_`{|}~" for char in cell) for cell in populated
        ) / max(sum(len(cell) for cell in populated), 1)

        reasons: list[str] = []
        quality = "ACCEPTED"
        if not populated:
            quality = "REJECTED"
            reasons.append("empty_row")
        elif symbol_ratio > 0.18:
            quality = "REJECTED"
            reasons.append("symbol_heavy")
        elif not label and not parsed_numbers:
            quality = "REJECTED"
            reasons.append("no_semantic_or_numeric_content")
        elif len(" ".join(populated)) > 420:
            quality = "REVIEW_REQUIRED"
            reasons.append("very_long_row")
        elif not label and parsed_numbers:
            quality = "REVIEW_REQUIRED"
            reasons.append("numeric_only_row")

        return {
            "row_index": index,
            "cells": cells,
            "label": label or None,
            "numeric_values": parsed_numbers,
            "quality": quality,
            "quality_reasons": reasons,
        }

    @classmethod
    def _number_value(cls, value: str) -> dict[str, Any] | None:
        compact = re.sub(r"\s+", "", value or "")
        if not cls.NUMBER_RE.fullmatch(compact):
            return None
        negative = compact.startswith("(") and compact.endswith(")")
        percent = compact.endswith("%")
        pence = compact.endswith("p")
        cleaned = re.sub(r"[£$€₹,%p()]", "", compact).replace(",", "")
        try:
            number = Decimal(cleaned)
        except InvalidOperation:
            return None
        if negative:
            number = -number
        return {
            "raw": value,
            "value": str(number),
            "is_percent": percent,
            "is_pence": pence,
        }

    @staticmethod
    def _remove_empty_columns(rows: list[list[str]]) -> list[list[str]]:
        if not rows:
            return []
        width = max(len(row) for row in rows)
        padded = [row + [""] * (width - len(row)) for row in rows]
        keep = [index for index in range(width) if any(row[index] for row in padded)]
        return [[row[index] for index in keep] for row in padded]

    @staticmethod
    def _remove_duplicate_rows(rows: list[list[str]]) -> list[list[str]]:
        output: list[list[str]] = []
        previous: tuple[str, ...] | None = None
        for row in rows:
            key = tuple(cell.casefold() for cell in row)
            if key != previous:
                output.append(row)
            previous = key
        return output

    @staticmethod
    def clean(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip().replace("−", "-")
