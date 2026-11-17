from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class NormalizedTable:
    original_rows: list[list[str]]
    normalized_rows: list[list[str]]
    markdown: str
    row_count: int
    column_count: int
    detected_periods: list[str]
    detected_units: list[str]
    warnings: list[str]


class TableNormalizer:
    PERIOD_RE = re.compile(r"\b(?:19|20)\d{2}\b")
    UNIT_PATTERNS = (
        (re.compile(r"£\s*[’']?000", re.I), "GBP thousands"),
        (re.compile(r"\$\s*[’']?000", re.I), "USD thousands"),
        (re.compile(r"€\s*[’']?000", re.I), "EUR thousands"),
        (re.compile(r"\bINR\b|₹", re.I), "INR"),
        (re.compile(r"%"), "percent"),
    )

    def normalize(self, rows: list[list[Any]]) -> NormalizedTable:
        original = [
            [self._clean(cell) for cell in row] for row in rows if row is not None
        ]
        original = [row for row in original if any(row)]
        if not original:
            raise ValueError("Table has no populated rows.")
        width = max(len(row) for row in original)
        padded = [row + [""] * (width - len(row)) for row in original]
        keep = [index for index in range(width) if any(row[index] for row in padded)]
        normalized = [[row[index] for index in keep] for row in padded]
        warnings: list[str] = []
        if len(normalized) < 2:
            warnings.append("fewer_than_two_rows")
        if len(keep) < 2:
            warnings.append("fewer_than_two_columns")
        if len({len(row) for row in original}) > 1:
            warnings.append("inconsistent_original_row_width")
        joined = " ".join(cell for row in normalized for cell in row)
        periods = sorted(set(self.PERIOD_RE.findall(joined)))
        units = [name for pattern, name in self.UNIT_PATTERNS if pattern.search(joined)]
        return NormalizedTable(
            original,
            normalized,
            self.to_markdown(normalized),
            len(normalized),
            len(keep),
            periods,
            units,
            warnings,
        )

    @staticmethod
    def _clean(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip().replace("−", "-")

    @staticmethod
    def to_markdown(rows: list[list[str]]) -> str:
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        padded = [row + [""] * (width - len(row)) for row in rows]

        def render(row):
            return (
                "| "
                + " | ".join(
                    cell.replace("|", "\\|").replace("\n", " ") for cell in row
                )
                + " |"
            )

        return "\n".join(
            [
                render(padded[0]),
                render(["---"] * width),
                *[render(row) for row in padded[1:]],
            ]
        )
