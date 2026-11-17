"""
layout_table_reconstructor.py

Reconstructs an LLM-friendly table from extracted PDF text elements.

Input:
    A list of items containing:
    - text
    - bbox.left
    - bbox.right
    - bbox.top
    - bbox.bottom
    - page_number
    - reading_order
    - label
    - hierarchy_level

Output:
    1. Structured JSON with:
       - detected columns
       - physical rows
       - cell assignments
       - header/body classification
       - reconstruction warnings
    2. Layout-preserving Markdown for an LLM.

No third-party packages are required.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

NUMBER_PATTERN = re.compile(
    r"""
    ^
    [£$€]?
    \(?
    [+-]?
    (?:
        \d{1,3}(?:,\d{3})+
        |
        \d+
    )
    (?:\.\d+)?
    %?
    \)?
    $
    """,
    re.VERBOSE,
)

DASH_PATTERN = re.compile(r"^[-–—]$")
YEAR_PATTERN = re.compile(r"^(?:19|20)\d{2}$")
UNIT_PATTERN = re.compile(
    r"""^(?:
        [£$€]\s*['’]?(?:000|m|mn|million)
        |
        ['’]?(?:000|m|mn|million)
        |
        %
    )$""",
    re.IGNORECASE | re.VERBOSE,
)
LEADER_PATTERN = re.compile(r"(?:\s*[.…·]{2,}\s*)+")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class TextElement:
    item_id: str
    text: str
    page_number: int
    reading_order: int
    label: str
    hierarchy_level: int
    left: float
    right: float
    top: float
    bottom: float

    @property
    def width(self) -> float:
        return max(self.right - self.left, 0.1)

    @property
    def height(self) -> float:
        return max(abs(self.top - self.bottom), 0.1)

    @property
    def x_center(self) -> float:
        return (self.left + self.right) / 2.0

    @property
    def y_center(self) -> float:
        return (self.top + self.bottom) / 2.0


@dataclass
class Token:
    text: str
    left: float
    right: float
    top: float
    bottom: float
    source_item_id: str
    reading_order: int

    @property
    def x_center(self) -> float:
        return (self.left + self.right) / 2.0

    @property
    def y_center(self) -> float:
        return (self.top + self.bottom) / 2.0


@dataclass
class PhysicalRow:
    row_id: int
    y_center: float
    elements: list[TextElement]

    @property
    def text(self) -> str:
        return clean_text(" ".join(element.text for element in self.elements))


@dataclass
class Column:
    column_id: int
    x_center: float


# ---------------------------------------------------------------------------
# Basic text classification
# ---------------------------------------------------------------------------

def clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = LEADER_PATTERN.sub(" ", text)
    return " ".join(text.split()).strip()


def is_numeric_token(text: str) -> bool:
    text = clean_text(text)
    return bool(NUMBER_PATTERN.fullmatch(text) or DASH_PATTERN.fullmatch(text))


def is_year(text: str) -> bool:
    return bool(YEAR_PATTERN.fullmatch(clean_text(text)))


def is_unit(text: str) -> bool:
    return bool(UNIT_PATTERN.fullmatch(clean_text(text)))


def contains_numeric_value(text: str) -> bool:
    return any(is_numeric_token(part) for part in clean_text(text).split())


def numeric_parts(text: str) -> list[str]:
    return [
        part
        for part in clean_text(text).split()
        if is_numeric_token(part)
    ]


# ---------------------------------------------------------------------------
# Input conversion
# ---------------------------------------------------------------------------

def to_elements(raw_items: Iterable[dict[str, Any]]) -> list[TextElement]:
    elements: list[TextElement] = []

    for item in raw_items:
        bbox = item.get("bbox") or {}
        text = clean_text(str(item.get("text", "")))
        if not text:
            continue

        required = {"left", "right", "top", "bottom"}
        if not required.issubset(bbox):
            continue

        elements.append(
            TextElement(
                item_id=str(item.get("item_id", "")),
                text=text,
                page_number=int(item.get("page_number", 0)),
                reading_order=int(item.get("reading_order", 0)),
                label=str(item.get("label", "")),
                hierarchy_level=int(item.get("hierarchy_level", 0) or 0),
                left=float(bbox["left"]),
                right=float(bbox["right"]),
                top=float(bbox["top"]),
                bottom=float(bbox["bottom"]),
            )
        )

    return sorted(
        elements,
        key=lambda element: (
            element.page_number,
            -element.y_center,
            element.left,
            element.reading_order,
        ),
    )


# ---------------------------------------------------------------------------
# Physical-row detection
# ---------------------------------------------------------------------------

def group_into_physical_rows(
    elements: list[TextElement],
    y_tolerance: Optional[float] = None,
) -> list[PhysicalRow]:
    if not elements:
        return []

    typical_height = statistics.median(element.height for element in elements)
    if y_tolerance is None:
        y_tolerance = max(2.5, typical_height * 0.45)

    grouped: list[list[TextElement]] = []

    for element in sorted(elements, key=lambda value: (-value.y_center, value.left)):
        best_group: Optional[list[TextElement]] = None
        best_distance = math.inf

        for group in grouped:
            group_y = statistics.mean(item.y_center for item in group)
            distance = abs(element.y_center - group_y)
            if distance <= y_tolerance and distance < best_distance:
                best_group = group
                best_distance = distance

        if best_group is None:
            grouped.append([element])
        else:
            best_group.append(element)

    rows: list[PhysicalRow] = []
    sorted_groups = sorted(
        grouped,
        key=lambda group: -statistics.mean(element.y_center for element in group),
    )

    for index, group in enumerate(sorted_groups):
        group.sort(key=lambda element: (element.left, element.reading_order))
        rows.append(
            PhysicalRow(
                row_id=index,
                y_center=statistics.mean(element.y_center for element in group),
                elements=group,
            )
        )

    return rows


# ---------------------------------------------------------------------------
# Splitting merged PDF spans
# ---------------------------------------------------------------------------

def split_element_by_whitespace(element: TextElement) -> list[Token]:
    """Split a span into tokens and estimate each token's x-position."""
    text = clean_text(element.text)
    matches = list(re.finditer(r"\S+", text))

    if not matches:
        return []

    if len(matches) == 1:
        return [
            Token(
                text=text,
                left=element.left,
                right=element.right,
                top=element.top,
                bottom=element.bottom,
                source_item_id=element.item_id,
                reading_order=element.reading_order,
            )
        ]

    total_chars = max(len(text), 1)
    char_width = element.width / total_chars
    tokens: list[Token] = []

    for match in matches:
        token_left = element.left + match.start() * char_width
        token_right = element.left + match.end() * char_width
        tokens.append(
            Token(
                text=match.group(),
                left=token_left,
                right=token_right,
                top=element.top,
                bottom=element.bottom,
                source_item_id=element.item_id,
                reading_order=element.reading_order,
            )
        )

    return tokens


def tokens_from_elements(elements: list[TextElement]) -> list[Token]:
    tokens: list[Token] = []
    for element in elements:
        tokens.extend(split_element_by_whitespace(element))
    return tokens


# ---------------------------------------------------------------------------
# Column-anchor detection
# ---------------------------------------------------------------------------

def cluster_positions(
    positions: list[float],
    tolerance: float,
) -> list[float]:
    if not positions:
        return []

    clusters: list[list[float]] = []
    for position in sorted(positions):
        if not clusters:
            clusters.append([position])
            continue

        current_center = statistics.mean(clusters[-1])
        if abs(position - current_center) <= tolerance:
            clusters[-1].append(position)
        else:
            clusters.append([position])

    return [statistics.median(cluster) for cluster in clusters]


def _unit_anchor_positions(rows: list[PhysicalRow]) -> tuple[list[float], Optional[int]]:
    """Return the strongest repeated-unit row and its token centres.

    A complete unit row such as six occurrences of £'000 is very strong evidence
    for six real columns. Merged Docling spans are split by whitespace first, so
    a span containing four units still contributes four geometric anchors.
    """
    candidates: list[tuple[int, list[float]]] = []
    for row in rows:
        positions: list[float] = []
        for element in row.elements:
            for token in split_element_by_whitespace(element):
                if is_unit(token.text):
                    positions.append(token.x_center)
        if len(positions) >= 2:
            candidates.append((row.row_id, sorted(positions)))
    if not candidates:
        return [], None
    # Majority means the row with the largest repeated unit pattern wins.
    # Ties prefer the earlier physical row, which is normally the header.
    row_id, positions = max(candidates, key=lambda x: (len(x[1]), -x[0]))
    return positions, row_id


def _numeric_evidence(rows: list[PhysicalRow]) -> list[float]:
    """Collect numeric geometry using right edges when reliable.

    Standalone financial values are normally right-aligned, so their right edge
    is stronger than their centre. Tokens estimated inside merged spans retain
    their estimated token centre because an exact right edge is unavailable.
    """
    positions: list[float] = []
    for row in rows:
        for element in row.elements:
            tokens = [
                token for token in split_element_by_whitespace(element)
                if is_numeric_token(token.text) and not is_year(token.text)
            ]
            if len(tokens) == 1 and is_numeric_token(clean_text(element.text)):
                positions.append(element.right)
            else:
                positions.extend(token.x_center for token in tokens)
    return positions


def _supported_unit_anchors(
    unit_positions: list[float],
    evidence: list[float],
    tolerance: float,
) -> tuple[list[float], list[int]]:
    """Snap slightly misplaced values to the nearest majority unit anchor."""
    if not unit_positions:
        return [], []
    supports = [sum(abs(value - anchor) <= tolerance for value in evidence) for anchor in unit_positions]
    # Keep the whole unit schema when most anchors have body support. Sparse total
    # columns are legitimate, so an individual zero-support unit is not deleted.
    supported_count = sum(value >= 1 for value in supports)
    if supported_count >= max(2, math.ceil(len(unit_positions) * 0.60)):
        return unit_positions, supports
    return [], supports


def detect_numeric_columns(
    rows: list[PhysicalRow],
    x_tolerance: float = 13.0,
    minimum_support: int = 2,
) -> list[Column]:
    """Detect columns using unit/header majority first, then body geometry.

    Priority:
      1. Repeated unit positions confirmed by nearby body values.
      2. Majority clusters of right-aligned body values.
      3. Estimated token centres for merged numeric spans.
    """
    unit_positions, _ = _unit_anchor_positions(rows)
    evidence = _numeric_evidence(rows)
    unit_tolerance = max(14.0, x_tolerance * 1.35)
    preferred, _ = _supported_unit_anchors(unit_positions, evidence, unit_tolerance)
    if preferred:
        return [Column(column_id=i, x_center=x) for i, x in enumerate(preferred)]

    raw_centers = cluster_positions(evidence, tolerance=x_tolerance)
    supported_centers = []
    for center in raw_centers:
        support = sum(abs(position - center) <= x_tolerance for position in evidence)
        if support >= minimum_support:
            supported_centers.append(center)
    return [Column(column_id=i, x_center=x) for i, x in enumerate(sorted(supported_centers))]


def column_detection_diagnostics(rows: list[PhysicalRow], columns: list[Column], x_tolerance: float) -> dict[str, Any]:
    units, unit_row = _unit_anchor_positions(rows)
    evidence = _numeric_evidence(rows)
    _, supports = _supported_unit_anchors(units, evidence, max(14.0, x_tolerance * 1.35))
    method = "unit_majority_confirmed_by_body" if units and len(columns) == len(units) else "body_majority_geometry"
    return {
        "method": method,
        "unit_row_id": unit_row,
        "unit_anchor_count": len(units),
        "unit_anchor_support": supports,
        "numeric_evidence_count": len(evidence),
        "selected_column_count": len(columns),
    }

def nearest_column(
    x_center: float,
    columns: list[Column],
    max_distance: Optional[float] = None,
) -> Optional[int]:
    if not columns:
        return None

    closest = min(
        columns,
        key=lambda column: abs(column.x_center - x_center),
    )
    distance = abs(closest.x_center - x_center)

    if max_distance is not None and distance > max_distance:
        return None

    return closest.column_id


# ---------------------------------------------------------------------------
# Assigning numeric values to columns
# ---------------------------------------------------------------------------

def _column_gap(columns: list[Column]) -> float:
    if len(columns) > 1:
        return statistics.median(
            columns[index + 1].x_center - columns[index].x_center
            for index in range(len(columns) - 1)
        )
    return 40.0


def _numeric_zone_start(columns: list[Column]) -> float:
    first_column_x = columns[0].x_center
    return first_column_x - min(25.0, _column_gap(columns) * 0.45)


def assign_numeric_tokens_with_audit(
    row: PhysicalRow,
    columns: list[Column],
) -> tuple[dict[int, list[str]], dict[str, Any]]:
    """Assign numeric tokens to columns and account for every token.

    No numeric token is silently dropped. Tokens that are too far from every
    detected column are returned as ``unassigned`` so the caller can keep them
    in the row label and raise a review warning.
    """
    assignments: dict[int, list[str]] = {
        column.column_id: [] for column in columns
    }
    audit = {
        "source_numeric_token_count": 0,
        "assigned_numeric_token_count": 0,
        "label_numeric_token_count": 0,
        "unassigned_numeric_token_count": 0,
        "unassigned_tokens": [],
        "duplicate_assignments": 0,
    }
    if not columns:
        return assignments, audit

    gap = _column_gap(columns)
    numeric_zone_start = _numeric_zone_start(columns)
    assignments_seen: set[tuple[str, int, float]] = set()

    for element in row.elements:
        for token in split_element_by_whitespace(element):
            if not is_numeric_token(token.text):
                continue
            audit["source_numeric_token_count"] += 1

            if token.x_center < numeric_zone_start:
                audit["label_numeric_token_count"] += 1
                continue

            column_id = nearest_column(token.x_center, columns)
            if column_id is None:
                audit["unassigned_numeric_token_count"] += 1
                audit["unassigned_tokens"].append(
                    {"text": token.text, "x": round(token.x_center, 3)}
                )
                continue

            distance = abs(columns[column_id].x_center - token.x_center)
            if distance > gap * 0.90:
                audit["unassigned_numeric_token_count"] += 1
                audit["unassigned_tokens"].append(
                    {
                        "text": token.text,
                        "x": round(token.x_center, 3),
                        "nearest_column": column_id,
                        "distance": round(distance, 3),
                    }
                )
                continue

            key = (token.text, column_id, round(token.x_center, 3))
            if key in assignments_seen:
                audit["duplicate_assignments"] += 1
                continue
            assignments_seen.add(key)
            assignments[column_id].append(token.text)
            audit["assigned_numeric_token_count"] += 1

    return assignments, audit


def assign_numeric_tokens(
    row: PhysicalRow,
    columns: list[Column],
) -> dict[int, list[str]]:
    """Backward-compatible wrapper used by visual/debug scripts."""
    assignments, _ = assign_numeric_tokens_with_audit(row, columns)
    return assignments

def row_label_text(
    row: PhysicalRow,
    first_numeric_column_x: float,
) -> str:
    label_parts: list[tuple[float, int, str]] = []

    for element in row.elements:
        tokens = split_element_by_whitespace(element)
        retained_words: list[str] = []

        for token in tokens:
            # Everything clearly before the first column belongs to the label.
            # This intentionally preserves "-" in "- assets".
            if token.x_center < first_numeric_column_x - 20:
                retained_words.append(token.text)
            elif not is_numeric_token(token.text):
                retained_words.append(token.text)

        text = clean_text(" ".join(retained_words))

        if text:
            label_parts.append(
                (
                    element.left,
                    element.reading_order,
                    text,
                )
            )

    return clean_text(
        " ".join(
            text
            for _, _, text in sorted(label_parts)
        )
    )


# ---------------------------------------------------------------------------
# Logical-row reconstruction
# ---------------------------------------------------------------------------

def _pending_section_rows(
    pending: list[dict[str, Any]],
    column_count: int,
) -> list[dict[str, Any]]:
    return [
        {
            "row_type": "section",
            "label": item["label"],
            "cells": [None] * column_count,
            "source_item_ids": item["source_item_ids"],
            "y_center": item["y_center"],
            "unassigned_numeric_tokens": [],
        }
        for item in pending
        if item["label"]
    ]


def _continuation_split(
    pending: list[dict[str, Any]],
    data_label: str,
) -> int:
    """Return how many pending label rows are true section rows.

    ``Profit`` + ``Segment operating`` + ``profit`` must become a section row
    ``Profit`` and a data row ``Segment operating profit``. A single pending
    line such as ``Share of profit of`` followed by ``associate company`` is a
    continuation and must be merged.
    """
    if not pending:
        return 0
    labels = [item["label"] for item in pending]
    lower_indexes = [index for index, label in enumerate(labels) if label[:1].islower()]

    if lower_indexes:
        # "Profit before taxation" + "and movement in fair" + "swap" is one
        # wrapped data label. "Profit" + "Segment operating" + "profit" keeps
        # Profit as a section because the next wrapped line starts at the last
        # title-case row.
        return max(0, lower_indexes[0] - 1)
    if data_label[:1].islower():
        if len(labels) == 1:
            return 0
        return len(labels) - 1
    return len(labels)


def merge_multiline_labels(
    rows: list[PhysicalRow],
    columns: list[Column],
    vertical_gap_multiplier: float = 1.7,
) -> list[dict[str, Any]]:
    if not rows or not columns:
        return []

    row_gaps = [
        abs(rows[index].y_center - rows[index + 1].y_center)
        for index in range(len(rows) - 1)
        if rows[index].y_center != rows[index + 1].y_center
    ]
    typical_gap = statistics.median(row_gaps) if row_gaps else 10.0
    max_merge_gap = typical_gap * vertical_gap_multiplier
    first_column_x = columns[0].x_center

    logical_rows: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    previous_y: Optional[float] = None

    for row in rows:
        values, row_audit = assign_numeric_tokens_with_audit(row, columns)
        has_values = any(values[column.column_id] for column in columns)
        label = row_label_text(row, first_column_x)
        source_ids = [element.item_id for element in row.elements]

        if (
            previous_y is not None
            and abs(previous_y - row.y_center) > max_merge_gap
            and pending
        ):
            logical_rows.extend(_pending_section_rows(pending, len(columns)))
            pending = []

        if has_values:
            section_count = _continuation_split(pending, label)
            logical_rows.extend(
                _pending_section_rows(pending[:section_count], len(columns))
            )
            continuation = pending[section_count:]
            full_label = clean_text(
                " ".join([item["label"] for item in continuation] + [label])
            )
            continuation_ids = [
                item_id
                for item in continuation
                for item_id in item["source_item_ids"]
            ]
            unassigned = [
                token["text"] for token in row_audit["unassigned_tokens"]
            ]
            if unassigned:
                full_label = clean_text(full_label + " " + " ".join(unassigned))
            logical_rows.append(
                {
                    "row_type": "data",
                    "label": full_label,
                    "cells": [
                        " ".join(values[column.column_id]) or None
                        for column in columns
                    ],
                    "source_item_ids": continuation_ids + source_ids,
                    "y_center": row.y_center,
                    "unassigned_numeric_tokens": unassigned,
                }
            )
            pending = []
        elif label:
            pending.append(
                {
                    "label": label,
                    "source_item_ids": source_ids,
                    "y_center": row.y_center,
                }
            )

        previous_y = row.y_center

    logical_rows.extend(_pending_section_rows(pending, len(columns)))
    return logical_rows


# ---------------------------------------------------------------------------
# Header reconstruction
# ---------------------------------------------------------------------------

HEADER_PERIOD_RE = re.compile(
    r"\b(?:year|period|quarter|half[ -]?year)\s+ended\b|\bas at\b", re.I
)


def detect_first_body_row_index(rows: list[PhysicalRow]) -> int:
    for index, row in enumerate(rows):
        values: list[str] = []
        for element in row.elements:
            values.extend(numeric_parts(element.text))
        non_year_values = [value for value in values if not is_year(value)]
        if len(non_year_values) >= 2:
            return index
    return len(rows)


def _header_row_signal(row: PhysicalRow) -> bool:
    if len(row.text.split()) > 14:
        return False
    tokens = [
        token
        for element in row.elements
        for token in split_element_by_whitespace(element)
    ]
    if any(is_unit(token.text) for token in tokens):
        return True
    if HEADER_PERIOD_RE.search(row.text):
        return True
    years = [token for token in tokens if is_year(token.text)]
    return len(years) >= 2


def _trim_leading_narrative(rows: list[PhysicalRow]) -> list[PhysicalRow]:
    """Drop prose accidentally included before the first real header block."""
    header_indexes = [
        index for index, row in enumerate(rows) if _header_row_signal(row)
    ]
    if not header_indexes:
        return rows
    first_header = header_indexes[0]
    leading = rows[:first_header]
    if not leading:
        return rows
    prose = any(len(row.text.split()) >= 18 for row in leading)
    no_values = all(not numeric_parts(row.text) for row in leading)
    if prose or no_values:
        # Section labels that accidentally entered the table region are also
        # emitted as section headings by the parser. Keeping them out of the
        # table prevents a real body row from being misclassified as a header.
        return rows[first_header:]
    return rows


def detect_header_body_boundary(rows: list[PhysicalRow]) -> tuple[int, int]:
    """Return ``(header_row_count, first_body_index)``.

    The old implementation treated *every* row before the first multi-number
    row as a header. That converted real body rows such as ``Revenue`` into
    header rows. The boundary now ends at the last real header signal (unit,
    period, or repeated-year row). Non-numeric rows after that signal stay in
    the body as section rows.
    """
    first_body = detect_first_body_row_index(rows)
    signals = [
        index
        for index in range(first_body)
        if _header_row_signal(rows[index])
    ]
    header_count = max(signals) + 1 if signals else 0
    return header_count, header_count


def assign_header_tokens(
    header_rows: list[PhysicalRow],
    columns: list[Column],
) -> list[dict[str, Any]]:
    reconstructed: list[dict[str, Any]] = []
    if not columns:
        return reconstructed

    column_spacing = (
        statistics.median(
            columns[index + 1].x_center - columns[index].x_center
            for index in range(len(columns) - 1)
        )
        if len(columns) > 1
        else 50.0
    )

    for row in header_rows:
        cells: list[list[str]] = [[] for _ in columns]
        left_labels: list[str] = []
        spanning_elements: list[dict[str, Any]] = []

        for element in row.elements:
            if element.right < columns[0].x_center - column_spacing * 0.45:
                left_labels.append(element.text)
                continue

            overlapping_columns = [
                column.column_id
                for column in columns
                if element.left - 5 <= column.x_center <= element.right + 5
            ]

            if is_year(element.text) or len(overlapping_columns) > 1:
                spanning_elements.append(
                    {
                        "text": element.text,
                        "left": element.left,
                        "right": element.right,
                        "center": element.x_center,
                        "candidate_columns": overlapping_columns,
                    }
                )

            tokens = split_element_by_whitespace(element)
            for token in tokens:
                column_id = nearest_column(
                    token.x_center,
                    columns,
                    max_distance=column_spacing * 0.70,
                )
                if column_id is not None:
                    cells[column_id].append(token.text)

        reconstructed.append(
            {
                "label": clean_text(" ".join(left_labels)),
                "cells": [
                    clean_text(" ".join(cell)) or None
                    for cell in cells
                ],
                "spans": spanning_elements,
                "source_item_ids": [
                    element.item_id for element in row.elements
                ],
                "y_center": row.y_center,
            }
        )

    return reconstructed


# ---------------------------------------------------------------------------
# Row classification and validation
# ---------------------------------------------------------------------------

def classify_logical_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        populated = [cell for cell in row["cells"] if cell is not None]
        if not populated:
            row["row_type"] = "section"
        elif row["label"].lower().startswith("total"):
            row["row_type"] = "total"
        else:
            row["row_type"] = "data"


def numeric_audit(
    body_rows: list[PhysicalRow],
    logical_rows: list[dict[str, Any]],
    columns: list[Column],
) -> dict[str, Any]:
    totals = {
        "source_numeric_token_count": 0,
        "assigned_numeric_token_count": 0,
        "label_numeric_token_count": 0,
        "unassigned_numeric_token_count": 0,
        "duplicate_assignments": 0,
        "unassigned_tokens": [],
    }
    for row in body_rows:
        _, audit = assign_numeric_tokens_with_audit(row, columns)
        for key in (
            "source_numeric_token_count",
            "assigned_numeric_token_count",
            "label_numeric_token_count",
            "unassigned_numeric_token_count",
            "duplicate_assignments",
        ):
            totals[key] += int(audit.get(key, 0))
        totals["unassigned_tokens"].extend(audit.get("unassigned_tokens", []))

    multi_value_cells = []
    data_row_count = 0
    for row in logical_rows:
        if row["row_type"] not in {"data", "total"}:
            continue
        data_row_count += 1
        for index, cell in enumerate(row["cells"]):
            if cell and len(numeric_parts(cell)) > 1:
                multi_value_cells.append(
                    {
                        "row_label": row["label"],
                        "column_index": index,
                        "cell": cell,
                    }
                )

    totals.update(
        {
            "data_row_count": data_row_count,
            "cells_with_multiple_values": len(multi_value_cells),
            "multi_value_cells": multi_value_cells[:20],
            "reconciled": (
                totals["source_numeric_token_count"]
                == totals["assigned_numeric_token_count"]
                + totals["label_numeric_token_count"]
                + totals["unassigned_numeric_token_count"]
            ),
        }
    )
    return totals


def make_warnings(
    structured_headers: list[dict[str, Any]],
    logical_rows: list[dict[str, Any]],
    columns: list[Column],
    audit: dict[str, Any] | None = None,
) -> list[str]:
    warnings: list[str] = []

    if not columns:
        warnings.append("No stable numeric columns were detected.")
        return warnings

    if not structured_headers:
        warnings.append(
            "No header rows were detected above the first numeric body row."
        )

    if not any(row["row_type"] in {"data", "total"} for row in logical_rows):
        warnings.append("No numeric body rows were reconstructed.")

    if audit:
        if not audit["reconciled"]:
            warnings.append(
                "Numeric-token reconciliation failed: "
                f"{audit['source_numeric_token_count']} source tokens, "
                f"{audit['assigned_numeric_token_count']} assigned, "
                f"{audit['label_numeric_token_count']} retained in labels, "
                f"{audit['unassigned_numeric_token_count']} unassigned."
            )
        if audit["unassigned_numeric_token_count"]:
            preview = ", ".join(
                f"'{token['text']}'"
                for token in audit["unassigned_tokens"][:5]
            )
            warnings.append(
                "Some numeric tokens could not be assigned to a stable column; "
                f"they were retained in row labels and flagged: {preview}."
            )
        if audit["cells_with_multiple_values"]:
            warnings.append(
                f"{audit['cells_with_multiple_values']} reconstructed cell(s) "
                "contain multiple numeric tokens; review column boundaries."
            )

    return list(dict.fromkeys(warnings))


# ---------------------------------------------------------------------------
# Main reconstruction
# ---------------------------------------------------------------------------

def _column_labels(
    structured_headers: list[dict[str, Any]],
    column_count: int,
) -> list[str]:
    labels: list[str] = []
    for index in range(column_count):
        values = []
        for header in structured_headers:
            value = header["cells"][index] if index < len(header["cells"]) else None
            if value and value not in values:
                values.append(value)
        labels.append(" / ".join(values) or f"Column {index + 1}")
    return labels


def reconstruct_table(
    raw_items: list[dict[str, Any]],
    y_tolerance: Optional[float] = None,
    x_tolerance: float = 13.0,
) -> dict[str, Any]:
    elements = to_elements(raw_items)
    if not elements:
        raise ValueError("No valid text elements were supplied.")

    pages = sorted({element.page_number for element in elements})
    physical_rows = _trim_leading_narrative(
        group_into_physical_rows(elements, y_tolerance=y_tolerance)
    )
    columns = detect_numeric_columns(
        physical_rows,
        x_tolerance=x_tolerance,
    )

    if not columns:
        raise ValueError(
            "Could not detect numeric table columns. "
            "Check whether the supplied region contains body rows."
        )

    header_count, body_start = detect_header_body_boundary(physical_rows)
    header_rows = physical_rows[:header_count]
    body_rows = physical_rows[body_start:]

    structured_headers = assign_header_tokens(
        header_rows,
        columns,
    )
    logical_rows = merge_multiline_labels(
        body_rows,
        columns,
    )
    classify_logical_rows(logical_rows)
    audit = numeric_audit(body_rows, logical_rows, columns)

    header_tokens = [
        token
        for row in header_rows
        for element in row.elements
        for token in split_element_by_whitespace(element)
    ]
    detected_periods = sorted(
        {
            token.text
            for token in header_tokens
            if is_year(token.text)
        }
    )
    detected_units = sorted(
        {
            token.text
            for token in header_tokens
            if is_unit(token.text)
        }
    )
    column_labels = _column_labels(structured_headers, len(columns))

    row_records = [
        {
            "row_index": index,
            "row_type": row["row_type"],
            "label": row["label"],
            "cells": row["cells"],
            "source_item_ids": row["source_item_ids"],
        }
        for index, row in enumerate(logical_rows)
    ]
    raw_rows = [
        {
            "row_type": "header",
            "label": header["label"],
            "cells": header["cells"],
            "spans": header.get("spans", []),
            "source_item_ids": header["source_item_ids"],
        }
        for header in structured_headers
    ] + row_records
    normalized_rows = [
        [header["label"]] + header["cells"]
        for header in structured_headers
    ] + [
        [row["label"]] + row["cells"]
        for row in logical_rows
    ]

    return {
        "page_numbers": pages,
        "coordinate_origin": "BOTTOMLEFT",
        "column_detection": column_detection_diagnostics(
            physical_rows, columns, x_tolerance
        ),
        "column_count": len(columns),
        "columns": [
            {
                "column_id": column.column_id,
                "x_center": round(column.x_center, 3),
            }
            for column in columns
        ],
        "column_labels": column_labels,
        "header_rows": structured_headers,
        "body_rows": logical_rows,
        "row_records": row_records,
        "raw_rows": raw_rows,
        "normalized_rows": normalized_rows,
        "detected_periods": detected_periods,
        "detected_units": detected_units,
        "numeric_audit": audit,
        "source_item_ids": sorted(
            {element.item_id for element in elements if element.item_id}
        ),
        "warnings": make_warnings(
            structured_headers,
            logical_rows,
            columns,
            audit,
        ),
    }


# ---------------------------------------------------------------------------
# LLM-friendly output
# ---------------------------------------------------------------------------

def escape_markdown(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", r"\|").replace("\n", " ")


def to_layout_markdown(table: dict[str, Any]) -> str:
    column_count = table["column_count"]
    lines = [
        "<!--",
        "TABLE RECONSTRUCTED FROM DOCLING TEXT GEOMETRY.",
        "Header and row-label text may contain extraction noise (OCR, merged spans, repeated headers).",
        "Column positions and numeric cells are the primary evidence; do not rewrite numeric values.",
        "Unassigned numeric tokens are retained in row labels and flagged in the warnings.",
        "Blank cells may be structurally meaningful.",
        "-->",
        "",
    ]

    labels = table.get("column_labels") or [
        f"Column {index + 1}" for index in range(column_count)
    ]
    headers = ["Row label"] + labels
    lines.append("| " + " | ".join(headers) + " |")
    lines.append(
        "| "
        + " | ".join(["---"] + ["---:"] * column_count)
        + " |"
    )

    for header in table["header_rows"]:
        row = [header["label"]] + header["cells"]
        lines.append(
            "| "
            + " | ".join(escape_markdown(value) for value in row)
            + " |"
        )
        for span in header.get("spans", []):
            candidates = [
                column_id + 1
                for column_id in span.get("candidate_columns", [])
            ]
            candidate_text = (
                ", ".join(map(str, candidates))
                if candidates
                else "nearest column by center"
            )
            lines.append(
                f"<!-- Header span: '{escape_markdown(span['text'])}' "
                f"covers candidate columns {candidate_text}; "
                f"x={span['left']:.2f}..{span['right']:.2f}. -->"
            )

    for row in table["body_rows"]:
        label = row["label"]
        if row["row_type"] in {"section", "total"}:
            label = f"**{label}**"
        values = [label] + row["cells"]
        lines.append(
            "| "
            + " | ".join(escape_markdown(value) for value in values)
            + " |"
        )

    if table["warnings"]:
        lines.extend(["", "### Reconstruction warnings"])
        for warning in table["warnings"]:
            lines.append(f"- {warning}")

    return "\n".join(lines)


def build_llm_payload(table: dict[str, Any]) -> dict[str, Any]:
    return {
        "instruction": (
            "Use this geometry-derived grid as financial evidence. Header text "
            "and row labels may be noisy or merged; rely on column positions, "
            "row order, and numeric cells. Never invent, round, or alter a "
            "numeric value. Preserve negatives shown in parentheses."
        ),
        "column_positions": [
            column["x_center"] for column in table["columns"]
        ],
        "column_labels": table.get("column_labels", []),
        "detected_periods": table.get("detected_periods", []),
        "detected_units": table.get("detected_units", []),
        "numeric_audit": table.get("numeric_audit", {}),
        "header_rows": table["header_rows"],
        "body_rows": [
            {
                "type": row["row_type"],
                "label": row["label"],
                "cells": row["cells"],
                "source_item_ids": row.get("source_item_ids", []),
            }
            for row in table["body_rows"]
        ],
        "warnings": table["warnings"],
    }



# Compatibility with the existing visual_table_test.py and parser connector.
def markdown_table(table: dict[str, Any]) -> str:
    return to_layout_markdown(table)

# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def load_items(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    if isinstance(data, list):
        return data

    for key in ("items", "elements", "content", "blocks"):
        value = data.get(key)
        if isinstance(value, list):
            return value

    raise ValueError(
        "Input JSON must be a list or contain an "
        "items/elements/content/blocks list."
    )


def save_results(
    table: dict[str, Any],
    output_prefix: str = "reconstructed_table",
) -> None:
    Path(f"{output_prefix}.json").write_text(
        json.dumps(table, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    Path(f"{output_prefix}.md").write_text(
        to_layout_markdown(table),
        encoding="utf-8",
    )
    Path(f"{output_prefix}_llm.json").write_text(
        json.dumps(
            build_llm_payload(table),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Reconstruct a table from layout-aware PDF extraction."
    )
    parser.add_argument(
        "input_json",
        help="JSON containing extracted table text elements.",
    )
    parser.add_argument(
        "--output-prefix",
        default="reconstructed_table",
        help="Output filename prefix.",
    )
    parser.add_argument(
        "--x-tolerance",
        type=float,
        default=13.0,
        help="Column clustering tolerance in PDF points.",
    )
    parser.add_argument(
        "--y-tolerance",
        type=float,
        default=None,
        help="Optional physical-row tolerance in PDF points.",
    )
    args = parser.parse_args()

    items = load_items(args.input_json)
    reconstructed = reconstruct_table(
        items,
        y_tolerance=args.y_tolerance,
        x_tolerance=args.x_tolerance,
    )
    save_results(
        reconstructed,
        output_prefix=args.output_prefix,
    )
    print(to_layout_markdown(reconstructed))
