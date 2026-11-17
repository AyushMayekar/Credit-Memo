from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import pymupdf


@dataclass(frozen=True, slots=True)
class HeadingDecision:
    classification: str
    score: int
    level: int | None
    reasons: list[str]


@dataclass(frozen=True, slots=True)
class TableDecision:
    classification: str
    score: int
    reasons: list[str]
    populated_cell_ratio: float
    numeric_cell_ratio: float
    row_width_consistency: float


class DocumentQualityRules:
    """Deterministic quality rules for headings, tables, charts, and margins."""

    SENTENCE_ENDINGS = (".", ";", ",")
    CONTINUED_RE = re.compile(r"\s*\(continued\)\s*$", re.IGNORECASE)
    NUMBER_ONLY_RE = re.compile(r"^[\s£$€₹(),.\-+%\d…]+$")
    YEAR_UNIT_RE = re.compile(
        r"^(?:20\d{2}\s*){1,4}(?:£[’']?000|\$[’']?000|%|£|\$|€|₹|\s)*$",
        re.IGNORECASE,
    )
    DATE_SUBTITLE_RE = re.compile(
        r"^(?:for the year ended|at|as at)\s+\d{1,2}(?:st|nd|rd|th)?\s+"
        r"[A-Za-z]+,?\s+20\d{2}$",
        re.IGNORECASE,
    )
    PERSON_NAME_RE = re.compile(
        r"^(?:(?:Mr|Mrs|Ms|Dr|Sir)\.?\s+)?" r"(?:[A-Z]\.?\s+){0,4}[A-Z][A-Za-z’'\-]+$"
    )
    SIGNATURE_ROLE_TERMS = {
        "chairman",
        "secretary",
        "director",
        "managing director",
        "by order of the board",
        "registered office",
    }
    TABLE_HEADER_TERMS = {
        "year",
        "2023",
        "2022",
        "2021",
        "total",
        "note",
        "group",
        "company",
        "revenue",
        "assets",
        "liabilities",
        "profit",
        "loss",
        "cash",
        "£000",
        "£’000",
        "percentage",
        "%",
        "description",
        "amount",
        "balance",
        "performance",
        "measure",
        "risk",
        "impact",
    }

    @staticmethod
    def normalize_text(value: str) -> str:
        value = re.sub(r"\s+", " ", value or "").strip()
        return DocumentQualityRules.CONTINUED_RE.sub("", value).strip()

    @classmethod
    def build_repeated_margin_signatures(
        cls,
        pages: list[dict[str, Any]],
        top_ratio: float = 0.055,
        bottom_ratio: float = 0.055,
        minimum_repetitions: int = 3,
        coordinate_tolerance: float = 8.0,
    ) -> set[str]:
        """Find text repeated at consistent extreme-margin coordinates.

        Repetition alone is insufficient. A signature is returned only when it
        appears in the extreme margin and at approximately the same y-position.
        This avoids treating legitimate recurring continuation titles at y~66 as
        headers when the true page header is usually closer to y~31.
        """
        occurrences: dict[str, list[tuple[int, float]]] = defaultdict(list)

        for page in pages:
            page_no = int(page["page_number"])
            height = float(page.get("height_points") or 1)
            for block in page.get("text_blocks", []):
                bbox = block.get("bbox") or [0, 0, 0, 0]
                y0, y1 = float(bbox[1]), float(bbox[3])
                in_extreme_margin = y0 <= height * top_ratio or y1 >= height * (
                    1 - bottom_ratio
                )
                if not in_extreme_margin:
                    continue

                signature = cls.normalize_text(block.get("text", "")).casefold()
                if signature and len(signature) <= 160:
                    anchor_y = y0 if y0 <= height * top_ratio else y1
                    occurrences[signature].append((page_no, anchor_y))

        repeated: set[str] = set()
        for signature, items in occurrences.items():
            unique_pages = {page_no for page_no, _ in items}
            if len(unique_pages) < minimum_repetitions:
                continue
            y_values = [position for _, position in items]
            if max(y_values) - min(y_values) <= coordinate_tolerance:
                repeated.add(signature)
        return repeated

    @classmethod
    def score_heading(
        cls,
        block: dict[str, Any],
        *,
        page_height: float,
        body_font_size: float,
        previous_block: dict[str, Any] | None,
        repeated_margin_signatures: set[str],
        inside_table: bool,
    ) -> HeadingDecision:
        raw_text = re.sub(r"\s+", " ", block.get("text", "")).strip()
        is_continuation = bool(cls.CONTINUED_RE.search(raw_text))
        normalized = cls.normalize_text(raw_text)
        signature = normalized.casefold()
        bbox = block.get("bbox") or [0, 0, 0, 0]
        size = float(block.get("max_font_size") or 0)
        word_count = len(normalized.split())
        alpha_count = sum(char.isalpha() for char in normalized)
        uppercase_ratio = sum(char.isupper() for char in normalized) / max(
            alpha_count, 1
        )
        digit_ratio = sum(char.isdigit() for char in normalized) / max(
            len(normalized), 1
        )
        numeric_token_ratio = cls._numeric_token_ratio(normalized)
        ellipsis_count = normalized.count("…") + normalized.count("...")
        score = 0
        reasons: list[str] = []

        if not normalized:
            return HeadingDecision("BODY_TEXT", -99, None, ["empty"])
        if inside_table:
            return HeadingDecision("TABLE_CONTENT", -10, None, ["inside_table"])
        if signature in repeated_margin_signatures:
            return HeadingDecision(
                "HEADER_FOOTER", -10, None, ["repeated_extreme_margin_text"]
            )
        if cls.NUMBER_ONLY_RE.fullmatch(normalized) or cls.YEAR_UNIT_RE.fullmatch(
            normalized
        ):
            return HeadingDecision(
                "TABLE_CONTENT", -8, None, ["numeric_or_year_unit_row"]
            )
        if cls.DATE_SUBTITLE_RE.fullmatch(normalized):
            return HeadingDecision("BODY_TEXT", -6, None, ["date_subtitle"])
        if cls._looks_like_signature_or_name(normalized):
            return HeadingDecision("BODY_TEXT", -6, None, ["signature_or_name"])
        if numeric_token_ratio >= 0.45:
            return HeadingDecision(
                "TABLE_CONTENT", -7, None, ["table_style_numeric_tokens"]
            )
        if ellipsis_count >= 2 and digit_ratio >= 0.08:
            return HeadingDecision(
                "TABLE_CONTENT", -7, None, ["ellipsis_financial_row"]
            )

        if size >= body_font_size * 1.55:
            score += 4
            reasons.append("font_much_larger")
        elif size >= body_font_size * 1.28:
            score += 3
            reasons.append("font_larger")
        elif size >= body_font_size * 1.12:
            score += 1
            reasons.append("font_slightly_larger")

        if block.get("is_bold"):
            score += 1
            reasons.append("bold")
        if 1 <= word_count <= 10:
            score += 2
            reasons.append("short")
        elif word_count <= 16:
            score += 1
            reasons.append("moderate_length")
        else:
            score -= 3
            reasons.append("too_many_words")
        if len(normalized) > 160:
            score -= 3
            reasons.append("too_long")
        if uppercase_ratio >= 0.8 and word_count <= 12:
            score += 2
            reasons.append("mostly_uppercase")
        if digit_ratio >= 0.28:
            score -= 4
            reasons.append("number_heavy")
        elif numeric_token_ratio >= 0.25:
            score -= 2
            reasons.append("mixed_numeric_row")
        if normalized.endswith(cls.SENTENCE_ENDINGS):
            score -= 2
            reasons.append("sentence_punctuation")
        if ":" in normalized and word_count > 10:
            score -= 1
            reasons.append("paragraph_like_colon")
        if normalized.casefold().startswith(
            ("for the year ended", "at 30th april", "by order of the board")
        ):
            score -= 3
            reasons.append("subtitle_or_signature")

        if previous_block:
            previous_bbox = previous_block.get("bbox") or [0, 0, 0, 0]
            whitespace = max(float(bbox[1]) - float(previous_bbox[3]), 0)
            if whitespace >= body_font_size * 2.0:
                score += 2
                reasons.append("large_whitespace_above")
            elif whitespace >= body_font_size:
                score += 1
                reasons.append("whitespace_above")

        near_top = float(bbox[1]) <= page_height * 0.16
        if near_top and word_count <= 16:
            score += 1
            reasons.append("near_page_top")

        # A continuation is not a new section. It extends the earlier normalized
        # title during production hierarchy construction.
        if is_continuation and score >= 4:
            return HeadingDecision(
                "CONTINUATION_HEADING", score, None, reasons + ["continued_title"]
            )

        if score >= 7:
            level = 1 if (size >= body_font_size * 1.5 or uppercase_ratio >= 0.8) else 2
            return HeadingDecision("SECTION", score, level, reasons)
        if score >= 4:
            return HeadingDecision("SUBSECTION", score, 3, reasons)
        if score >= 2:
            return HeadingDecision("POSSIBLE_HEADING", score, None, reasons)
        return HeadingDecision("BODY_TEXT", score, None, reasons)

    @classmethod
    def score_table(
        cls,
        rows: list[list[Any]],
        *,
        bbox: list[float] | None,
        page: pymupdf.Page | None = None,
    ) -> TableDecision:
        normalized = [
            [re.sub(r"\s+", " ", str(cell or "")).strip() for cell in row]
            for row in rows
            if row is not None
        ]
        if not normalized:
            return TableDecision("REJECTED", -10, ["no_rows"], 0, 0, 0)

        row_count = len(normalized)
        widths = [len(row) for row in normalized]
        column_count = max(widths, default=0)
        cells = [cell for row in normalized for cell in row]
        populated = [cell for cell in cells if cell]
        populated_ratio = len(populated) / max(len(cells), 1)
        numeric = [cell for cell in populated if cls._looks_numeric(cell)]
        numeric_ratio = len(numeric) / max(len(populated), 1)
        width_consistency = sum(width == column_count for width in widths) / max(
            row_count, 1
        )
        meaningful_labels = [
            cell
            for cell in populated
            if re.search(r"[A-Za-z]{3,}", cell) and not cls.YEAR_UNIT_RE.fullmatch(cell)
        ]
        header_hits = sum(
            1
            for cell in (normalized[0] if normalized else [])
            if cls.normalize_text(cell).casefold() in cls.TABLE_HEADER_TERMS
            or any(
                term in cls.normalize_text(cell).casefold()
                for term in cls.TABLE_HEADER_TERMS
            )
        )

        score = 0
        reasons: list[str] = []
        if row_count >= 3:
            score += 2
            reasons.append("multiple_rows")
        else:
            score -= 2
            reasons.append("too_few_rows")
        if column_count >= 2:
            score += 2
            reasons.append("multiple_columns")
        else:
            score -= 3
            reasons.append("single_column")
        if populated_ratio >= 0.55:
            score += 3
            reasons.append("good_cell_density")
        elif populated_ratio >= 0.3:
            score += 1
            reasons.append("moderate_cell_density")
        else:
            score -= 4
            reasons.append("sparse_cells")
        if width_consistency >= 0.7:
            score += 2
            reasons.append("consistent_row_width")
        elif width_consistency < 0.4:
            score -= 2
            reasons.append("irregular_row_width")
        if len(meaningful_labels) >= 2:
            score += 2
            reasons.append("meaningful_labels")
        else:
            score -= 2
            reasons.append("few_meaningful_labels")
        if header_hits:
            score += 1
            reasons.append("header_signal")
        if numeric_ratio >= 0.2:
            score += 1
            reasons.append("numeric_data")

        if page is not None and bbox:
            chart_penalty, chart_reasons = cls._chart_shape_penalty(
                page, bbox, populated
            )
            score += chart_penalty
            reasons.extend(chart_reasons)

        if score >= 7:
            classification = "TABLE"
        elif score >= 4:
            classification = "TABLE_REVIEW_REQUIRED"
        elif score <= 0:
            classification = "VISUAL_CANDIDATE"
        else:
            classification = "REJECTED"

        return TableDecision(
            classification=classification,
            score=score,
            reasons=reasons,
            populated_cell_ratio=round(populated_ratio, 4),
            numeric_cell_ratio=round(numeric_ratio, 4),
            row_width_consistency=round(width_consistency, 4),
        )

    @staticmethod
    def _numeric_token_ratio(value: str) -> float:
        tokens = value.split()
        if not tokens:
            return 0.0
        numeric_tokens = 0
        for token in tokens:
            cleaned = re.sub(r"[£$€₹,%()….'’\-]", "", token)
            if cleaned.isdigit():
                numeric_tokens += 1
        return numeric_tokens / len(tokens)

    @classmethod
    def _looks_like_signature_or_name(cls, value: str) -> bool:
        lowered = value.casefold()
        if lowered in cls.SIGNATURE_ROLE_TERMS:
            return True
        lines = [line.strip() for line in re.split(r"[\n|]", value) if line.strip()]
        if any(line.casefold() in cls.SIGNATURE_ROLE_TERMS for line in lines):
            return True
        if len(value.split()) <= 5 and cls.PERSON_NAME_RE.fullmatch(value):
            return True
        if len(lines) <= 3 and any(
            role in lowered for role in ("chairman", "secretary", "director")
        ):
            return True
        return False

    @staticmethod
    def _looks_numeric(value: str) -> bool:
        cleaned = re.sub(r"[£$€₹,%()\s]", "", value)
        return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", cleaned))

    @classmethod
    def _chart_shape_penalty(
        cls,
        page: pymupdf.Page,
        bbox: list[float],
        populated_cells: list[str],
    ) -> tuple[int, list[str]]:
        target = pymupdf.Rect(bbox)
        filled_rectangles = 0
        drawing_count = 0
        thin_lines = 0
        try:
            drawings = page.get_drawings()
        except Exception:
            drawings = []

        for drawing in drawings:
            rect = drawing.get("rect")
            if not rect or rect.is_empty or not target.intersects(rect):
                continue
            drawing_count += 1
            if drawing.get("fill") is not None and rect.width > 3 and rect.height > 3:
                filled_rectangles += 1
            if min(rect.width, rect.height) <= 1.5:
                thin_lines += 1

        reasons: list[str] = []
        penalty = 0
        if filled_rectangles >= 5 and len(populated_cells) < filled_rectangles * 2:
            penalty -= 5
            reasons.append("bar_chart_pattern")
        if drawing_count >= 30 and len(populated_cells) < 10:
            penalty -= 4
            reasons.append("drawing_heavy_text_sparse")
        if thin_lines >= 2 and filled_rectangles >= 3:
            penalty -= 2
            reasons.append("axis_and_bars_pattern")
        return penalty, reasons
