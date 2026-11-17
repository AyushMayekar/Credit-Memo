"""Deterministic table-boundary detection for Docling extraction.json.

Detects candidate table regions only. It does not reconstruct tables.
Standard-library only.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NUMBER_RE = re.compile(
    r"(?<![\w.])(?:[£$€₹]\s*)?\(?[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?\)?(?![\w.])"
)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
PERIOD_RE = re.compile(
    r"\b(?:year|period|quarter|half[ -]?year)\s+ended\b|\bas at\b", re.I
)
UNIT_RE = re.compile(
    r"(?:£|\$|€|₹)\s*['’]?\s*(?:000|m|mn|million)\b|\bpercent(?:age)?\b|%", re.I
)
FINANCIAL_RE = re.compile(
    r"\b(?:revenue|profit|loss|total|assets?|liabilit(?:y|ies)|cash|tax|equity|costs?|segment|borrowings?|inventory|dividend|income|expenses?)\b",
    re.I,
)
PAGE_NUMBER_RE = re.compile(r"^\d{1,3}$")


@dataclass
class Item:
    raw: dict[str, Any]
    text: str
    page: int
    order: int
    item_type: str
    hierarchy: int
    left: float
    right: float
    top: float
    bottom: float
    visual_top: float
    visual_bottom: float

    @property
    def width(self) -> float:
        return max(0.1, self.right - self.left)

    @property
    def y(self) -> float:
        return (self.visual_top + self.visual_bottom) / 2


@dataclass
class Row:
    items: list[Item]
    y: float
    top: float
    bottom: float

    @property
    def text(self) -> str:
        return " ".join(x.text for x in self.items)

    @property
    def start_order(self) -> int:
        return min(x.order for x in self.items)

    @property
    def end_order(self) -> int:
        return max(x.order for x in self.items)


def clean(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "").replace("\u00ad", "")).strip()


def prepare(page: dict[str, Any]) -> list[Item]:
    height = float(page.get("height_points") or 1)
    out = []
    for raw in page.get("items") or []:
        b = raw.get("bbox") or {}
        text = clean(raw.get("text"))
        if not text or not all(k in b for k in ("left", "right", "top", "bottom")):
            continue
        l, r = sorted((float(b["left"]), float(b["right"])))
        a, z = float(b["top"]), float(b["bottom"])
        if "BOTTOMLEFT" in str(b.get("coord_origin", "")).upper():
            vt, vb = height - max(a, z), height - min(a, z)
        else:
            vt, vb = min(a, z), max(a, z)
        out.append(
            Item(
                raw,
                text,
                int(page["page_number"]),
                int(raw.get("reading_order") or 0),
                str(raw.get("item_type") or ""),
                int(raw.get("hierarchy_level") or 0),
                l,
                r,
                a,
                z,
                vt,
                vb,
            )
        )
    return sorted(out, key=lambda x: (x.y, x.left, x.order))


def group_rows(items: list[Item]) -> list[Row]:
    if not items:
        return []
    typical = statistics.median(max(0.1, x.visual_bottom - x.visual_top) for x in items)
    tol = max(2.2, typical * 0.45)
    groups = []
    for item in items:
        best = None
        dist = math.inf
        for group in groups:
            gy = statistics.median(x.y for x in group)
            d = abs(item.y - gy)
            if d <= tol and d < dist:
                best = group
                dist = d
        if best is None:
            groups.append([item])
        else:
            best.append(item)
    groups.sort(key=lambda g: statistics.median(x.y for x in g))
    return [
        Row(
            sorted(g, key=lambda x: (x.left, x.order)),
            statistics.median(x.y for x in g),
            min(x.visual_top for x in g),
            max(x.visual_bottom for x in g),
        )
        for g in groups
    ]


def nums(text: str) -> list[str]:
    return NUMBER_RE.findall(UNIT_RE.sub(" ", text))


def row_features(row: Row, page_width: float, page_height: float) -> dict[str, Any]:
    values = nums(row.text)
    years = YEAR_RE.findall(row.text)
    unit = bool(UNIT_RE.search(row.text))
    period = bool(PERIOD_RE.search(row.text))
    numeric_items = []
    for item in row.items:
        n = nums(item.text)
        if n:
            numeric_items.append(item)
    x_positions = [x.right for x in numeric_items]
    full_width = (
        max(x.right for x in row.items) - min(x.left for x in row.items)
    ) >= page_width * 0.68
    long_narrative = len(row.text.split()) >= 18 and len(values) <= 1
    heading = any(x.item_type == "heading" for x in row.items)
    footer = PAGE_NUMBER_RE.fullmatch(row.text) and row.bottom >= page_height * 0.90
    score = 0.0
    reasons = []
    if len(values) >= 2:
        score += 4
        reasons.append("multiple_values")
    elif len(values) == 1:
        score += 1
    if len(x_positions) >= 2:
        score += 2
        reasons.append("multiple_numeric_blocks")
    if years:
        score += 2
        reasons.append("year")
    if period:
        score += 2
        reasons.append("period_header")
    if unit:
        score += 3
        reasons.append("unit")
    if any(x.hierarchy >= 3 for x in row.items):
        score += 1
        reasons.append("deep_hierarchy")
    if FINANCIAL_RE.search(row.text) and len(row.text.split()) <= 12:
        score += 1
        reasons.append("financial_label")
    if heading:
        score -= 5
        reasons.append("heading")
    if long_narrative and full_width:
        score -= 5
        reasons.append("narrative")
    if footer:
        score -= 6
        reasons.append("footer_page_number")
    return {
        "score": score,
        "values": len(values),
        "x_positions": x_positions,
        "reasons": reasons,
        "heading": heading,
        "narrative": long_narrative and full_width,
        "footer": footer,
        "unit": unit,
        "period": period,
        "year": bool(years),
    }


UNIT_HEADER_RE = re.compile(
    r"(?:£|\$|€|₹)\s*['’]?\s*(?:000|m|mn|million)\b|(?:^|\s)%(?:\s|$)",
    re.I,
)


def header_evidence(row: Row) -> bool:
    """Return True when a row is plausibly a table header.

    A single year is not enough: financial rows often contain a year in a
    label or as a value. Repeated years, period phrases, and explicit unit
    rows are much stronger evidence. Percentages embedded in prose must not
    turn a data row into a new table header.
    """
    if len(row.text.split()) > 14:
        return False
    years = YEAR_RE.findall(row.text)
    return bool(
        UNIT_HEADER_RE.search(row.text)
        or PERIOD_RE.search(row.text)
        or len(years) >= 2
    )


def header_resets(rows: list[Row]) -> int:
    """Count internal header re-starts, a strong signal of merged tables."""
    resets = 0
    seen_header = False
    data_since_header = 0
    for row in rows:
        if header_evidence(row):
            if seen_header and data_since_header >= 2:
                resets += 1
            seen_header = True
            data_since_header = 0
        elif len(nums(row.text)) >= 2:
            data_since_header += 1
    return resets


def narrative_rows(rows: list[Row]) -> int:
    """Rows that look like prose rather than table rows.

    Docling often splits a numeric table row into a long label item and a
    separate number item. A threshold that is too low therefore classifies
    ordinary table rows as prose. Only clearly sentence-length rows count.
    """
    count = 0
    for row in rows:
        words = len(row.text.split())
        if words >= 18 and len(nums(row.text)) <= 1:
            count += 1
        elif words >= 30 and re.search(r"[.;]", row.text):
            # Narrative paragraphs can contain several numbers (percentages,
            # years). Sentence length plus punctuation is the stronger signal.
            count += 1
    return count


def alignment_score(
    rows: list[Row], features: list[dict[str, Any]], tolerance: float = 16
) -> tuple[float, int]:
    positions = [x for f in features for x in f["x_positions"]]
    if not positions:
        return 0.0, 0
    clusters = []
    for x in sorted(positions):
        if clusters and abs(x - statistics.median(clusters[-1])) <= tolerance:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    supported = [statistics.median(c) for c in clusters if len(c) >= 2]
    value_rows = [f for f in features if f["values"] >= 2]
    if not value_rows or len(supported) < 2:
        return 0.0, len(supported)
    aligned = 0
    for f in value_rows:
        hits = sum(
            any(abs(x - c) <= tolerance for c in supported) for x in f["x_positions"]
        )
        if hits >= min(2, len(f["x_positions"])):
            aligned += 1
    return aligned / len(value_rows), len(supported)


def rough_regions(
    rows: list[Row], feats: list[dict[str, Any]]
) -> list[tuple[int, int]]:
    regions = []
    start = None
    last_strong = None
    weak = 0
    for i, f in enumerate(feats):
        strong = f["score"] >= 3
        supportive = f["score"] >= 1 or (
            start is not None
            and FINANCIAL_RE.search(rows[i].text)
            and len(rows[i].text.split()) <= 12
        )
        hard_stop = f["heading"] or f["narrative"] or f["footer"]
        if start is None:
            look = feats[i : min(len(feats), i + 4)]
            if strong and sum(x["score"] >= 3 for x in look) >= 2:
                start = i
                last_strong = i
                weak = 0
        else:
            if hard_stop:
                if last_strong is not None:
                    regions.append((start, last_strong))
                start = None
                last_strong = None
                weak = 0
            elif strong or supportive:
                if strong:
                    last_strong = i
                weak = 0
            else:
                weak += 1
                if weak >= 2:
                    if last_strong is not None:
                        regions.append((start, last_strong))
                    start = None
                    last_strong = None
                    weak = 0
    if start is not None and last_strong is not None:
        regions.append((start, last_strong))
    return regions


def refine(
    start: int, end: int, rows: list[Row], feats: list[dict[str, Any]]
) -> tuple[int, int]:
    while start > 0 and start - 1 >= 0:
        f = feats[start - 1]
        gap = rows[start].top - rows[start - 1].bottom
        if (
            gap <= 20
            and not f["heading"]
            and not f["narrative"]
            and (f["unit"] or f["period"] or f["year"] or f["score"] >= 1)
        ):
            start -= 1
        else:
            break
    while end + 1 < len(rows):
        f = feats[end + 1]
        gap = rows[end + 1].top - rows[end].bottom
        if (
            gap <= 20
            and not f["heading"]
            and not f["narrative"]
            and not f["footer"]
            and (f["score"] >= 1 or FINANCIAL_RE.search(rows[end + 1].text))
        ):
            end += 1
        else:
            break
    return start, end

def trim_boundaries(
    start: int,
    end: int,
    rows: list[Row],
    feats: list[dict[str, Any]],
) -> tuple[int, int]:
    """Remove unrelated rows accidentally included around a detected table."""

    original_start = start
    original_end = end

    # ---------------------------------------------------------
    # Trim obvious unrelated content from the beginning.
    # ---------------------------------------------------------
    while start <= end:
        feature = feats[start]

        if feature["heading"]:
            start += 1
            continue

        if feature["narrative"]:
            start += 1
            continue

        if feature["footer"]:
            start += 1
            continue

        break

    # ---------------------------------------------------------
    # Prefer a period/year/unit row as the table start.
    #
    # Example:
    # Year ended 30th April, 2024
    # £'000 £'000 £'000
    # ---------------------------------------------------------
    header_start = None

    for index in range(start, min(end + 1, start + 8)):
        feature = feats[index]

        if feature["period"] or feature["unit"] or feature["year"]:
            header_start = index
            break

    if header_start is not None:
        start = header_start
    else:
        # No explicit table header was found.
        # Find the first stable table-like row.
        for index in range(start, end + 1):
            nearby = feats[index : min(end + 1, index + 4)]

            strong_rows = sum(
                feature["score"] >= 3
                for feature in nearby
            )

            if strong_rows >= 2:
                start = index
                break

    # ---------------------------------------------------------
    # Remove unrelated content from the end.
    # ---------------------------------------------------------
    while end >= start:
        feature = feats[end]
        row = rows[end]

        if feature["footer"]:
            end -= 1
            continue

        if feature["heading"]:
            end -= 1
            continue

        if feature["narrative"]:
            end -= 1
            continue

        # Remove isolated printed page numbers.
        if (
            PAGE_NUMBER_RE.fullmatch(row.text.strip())
            and feature["values"] <= 1
        ):
            end -= 1
            continue

        break

    # ---------------------------------------------------------
    # Remove trailing weak rows after the final real table row.
    # Keep short financial labels and value-bearing rows.
    # ---------------------------------------------------------
    last_useful = None

    for index in range(start, end + 1):
        feature = feats[index]
        row = rows[index]

        useful = (
            feature["values"] >= 1
            or feature["unit"]
            or feature["period"]
            or feature["year"]
            or (
                bool(FINANCIAL_RE.search(row.text))
                and len(row.text.split()) <= 12
            )
        )

        if useful and not feature["footer"]:
            last_useful = index

    if last_useful is not None:
        end = last_useful

    if start > end:
        return original_start, original_end

    return start, end

def detect_page(page: dict[str, Any]) -> list[dict[str, Any]]:
    items = prepare(page)
    rows = group_rows(items)
    width = float(page.get("width_points") or 1)
    height = float(page.get("height_points") or 1)
    feats = [row_features(r, width, height) for r in rows]
    out = []
    for idx, (s, e) in enumerate(rough_regions(rows, feats), 1):
        raw_start = s
        raw_end = e

        s, e = refine(s, e, rows, feats)
        s, e = trim_boundaries(s, e, rows, feats)
        region_rows = rows[s : e + 1]
        region_feats = feats[s : e + 1]
        value_rows = sum(f["values"] >= 2 for f in region_feats)
        align, cols = alignment_score(region_rows, region_feats)
        header = any(header_evidence(row) for row in region_rows)
        if value_rows < 3 or cols < 2 or align < 0.45:
            continue

        resets = header_resets(region_rows)
        prose_rows = narrative_rows(region_rows)
        physical_rows = len(region_rows)
        numeric_density = min(
            1.0,
            value_rows / max(1.0, physical_rows * 0.55),
        )
        prose_ratio = prose_rows / max(1, physical_rows)

        confidence = (
            0.32
            + 0.12 * min(value_rows, 8) / 8.0
            + 0.22 * align
            + 0.10 * min(cols, 8) / 8.0
            + (0.08 if header else 0.0)
            + 0.08 * numeric_density
            - 0.12 * min(resets, 3)
            - 0.18 * min(1.0, prose_ratio * 4.0)
        )
        confidence = max(0.0, min(1.0, confidence))

        region_warnings = []
        if not header:
            region_warnings.append("NO_PERIOD_OR_UNIT_HEADER")
        if resets:
            region_warnings.append("MULTIPLE_TABLE_HEADERS")
        if prose_rows:
            region_warnings.append("NARRATIVE_ROWS_INSIDE_REGION")
        if align < 0.70:
            region_warnings.append("LOW_COLUMN_ALIGNMENT")

        # A region can look geometrically excellent and still be a merged table
        # or narrative text with numbers. Never call those high confidence.
        high_confidence = (
            confidence >= 0.78
            and header
            and not resets
            and prose_rows == 0
            and align >= 0.70
        )
        classification = (
            "HIGH_CONFIDENCE"
            if high_confidence
            else "REVIEW_REQUIRED" if confidence >= 0.50 else "LOW_CONFIDENCE"
        )
        region_items = sorted(
            {
                str(x.raw.get("item_id") or f"P{x.page:04d}-O{x.order:05d}"): x
                for row in region_rows
                for x in row.items
            }.values(),
            key=lambda x: x.order,
        )
        out.append(
            {
                "region_id": f"P{int(page['page_number']):04d}-TR{idx:03d}",
                "page_number": int(page["page_number"]),
                "raw_reading_order_start": rows[raw_start].start_order,
                "raw_reading_order_end": rows[raw_end].end_order,
                "reading_order_start": min(x.order for x in region_items),
                "reading_order_end": max(x.order for x in region_items),
                "boundary_trimmed": (
                    raw_start != s or raw_end != e
                ),
                "rows_trimmed_from_start": s - raw_start,
                "rows_trimmed_from_end": raw_end - e,
                "source_item_ids": [
                    str(x.raw.get("item_id") or f"P{x.page:04d}-O{x.order:05d}")
                    for x in region_items
                ],
                "bbox": {
                    "left": round(min(x.left for x in region_items), 2),
                    "top": round(max(x.top for x in region_items), 2),
                    "right": round(max(x.right for x in region_items), 2),
                    "bottom": round(min(x.bottom for x in region_items), 2),
                    "coord_origin": str(
                        region_items[0]
                        .raw.get("bbox", {})
                        .get("coord_origin", "unknown")
                    ),
                },
                "features": {
                    "physical_rows": physical_rows,
                    "value_rows": value_rows,
                    "recurring_columns": cols,
                    "column_alignment": round(align, 4),
                    "header_evidence": header,
                    "header_resets": resets,
                    "narrative_rows": prose_rows,
                    "narrative_ratio": round(prose_ratio, 4),
                    "numeric_density": round(numeric_density, 4),
                },
                "confidence": round(confidence, 4),
                "classification": classification,
                "text_preview": " | ".join(r.text for r in region_rows[:5]),
                "warnings": region_warnings,
            }
        )
    return out


def render_html(regions: list[dict[str, Any]]) -> str:
    cards = []
    for r in regions:
        f = r["features"]
        cards.append(
            f"<section><h2>{html.escape(r['region_id'])}</h2><p><b>Page:</b> {r['page_number']} · <b>Reading order:</b> {r['reading_order_start']}-{r['reading_order_end']} · <b>Confidence:</b> {r['confidence']} ({r['classification']})</p><p>Rows: {f['physical_rows']} · Value rows: {f['value_rows']} · Columns: {f['recurring_columns']} · Alignment: {f['column_alignment']}</p><pre>{html.escape(r['text_preview'])}</pre></section>"
        )
    return (
        "<!doctype html><meta charset='utf-8'><style>body{font:14px Arial;margin:24px;background:#f7f7f7}section{background:white;border:1px solid #ccc;border-radius:8px;padding:16px;margin:12px 0}pre{white-space:pre-wrap}</style><h1>Detected table regions</h1>"
        + "".join(cards)
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input_json", type=Path)
    p.add_argument("--pages", nargs="*", type=int)
    p.add_argument("--output-dir", type=Path, default=Path("table-boundary-review"))
    a = p.parse_args()
    data = json.loads(a.input_json.read_text(encoding="utf-8"))
    pages = data.get("pages") or []
    if a.pages:
        pages = [x for x in pages if int(x.get("page_number", 0)) in set(a.pages)]
    regions = [r for page in pages for r in detect_page(page)]
    a.output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": str(a.input_json.resolve()),
        "processed_pages": [int(p["page_number"]) for p in pages],
        "region_count": len(regions),
        "regions": regions,
    }
    (a.output_dir / "table_regions.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (a.output_dir / "table_regions_review.html").write_text(
        render_html(regions), encoding="utf-8"
    )
    summary = {
        "processed_page_count": len(pages),
        "detected_region_count": len(regions),
        "high_confidence": sum(
            r["classification"] == "HIGH_CONFIDENCE" for r in regions
        ),
        "review_required": sum(
            r["classification"] == "REVIEW_REQUIRED" for r in regions
        ),
        "output_json": str((a.output_dir / "table_regions.json").resolve()),
        "output_html": str((a.output_dir / "table_regions_review.html").resolve()),
    }
    (a.output_dir / "table_regions_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
