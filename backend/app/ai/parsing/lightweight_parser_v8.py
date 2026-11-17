from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any

from app.ai.parsing.models import StructuralParsingResult
from app.ai.tables.processing_pipeline import TableProcessingPipeline
from scripts.table_boundary_detector import detect_page


class LightweightParsingError(Exception):
    pass


class LightweightParsingPipelineV8:
    """Conservative structural parser driven by raw Docling items.

    Tables are reconstructed from text geometry, then their source items are
    removed from the narrative stream. Everything else becomes a section-grounded
    record so hierarchical chunking can later attach children to the correct
    parent section.
    """

    VERSION = "lightweight-structural-parser-v8.1"
    SCHEMA_VERSION = "3.1"
    GARBAGE_SYMBOLS = set("!@#=<>^_`{|}~")
    CONTINUED_RE = re.compile(r"\s*\(continued\)\s*", re.I)
    MERGED_CONTINUATION_RE = re.compile(r"^(.*?)\s*\(continued\)\s+(.+)$", re.I)
    NUMBERED_RE = re.compile(
        r"^(?:C?\d{1,3})(?:(?:[.)])\s*(?=[A-Z])|\s+(?=[A-Z]))\S"
    )
    PAGE_NUMBER_RE = re.compile(r"^\d{1,3}$")
    DATE_SUBTITLE_RE = re.compile(r"^(?:for the year ended|as at|at)\b", re.I)
    PERSON_RE = re.compile(
        r"^(?:(?:Mr|Mrs|Ms|Dr|Sir)\.?\s+)?(?:[A-Z]\.?\s+){1,4}[A-Z][A-Za-z’'\-]+$"
    )
    FIELD_LABEL_RE = re.compile(
        r"^(?:directors?|auditors?|secretary|registered office|notes?)\s*:$", re.I
    )
    CONTENT_LABEL_RE = re.compile(
        r"^(?:.*(?:rates?|profile|analysis|breakdown)\s+(?:are|is)\s+as follows|currency profile.*)\s*:$",
        re.I,
    )
    MASTHEADS = {
        "goodwin plc",
        "financial statements",
        "notes to the financial statements",
        "group strategic report",
    }

    def __init__(self, parsed_root: Path | None = None) -> None:
        self.parsed_root = (parsed_root or Path("storage/parsed-v8")).resolve()
        self.parsed_root.mkdir(parents=True, exist_ok=True)

    def parse(
        self,
        *,
        extraction_path: Path,
        table_regions_path: Path | None = None,
        application_reference: str,
        document_reference: str,
    ) -> StructuralParsingResult:
        started = perf_counter()
        extraction_path = extraction_path.resolve()
        extraction = self._read(extraction_path)
        if not isinstance(extraction.get("pages"), list):
            raise LightweightParsingError("Extraction pages must be a list")

        target = (
            self.parsed_root
            / self._safe(application_reference)
            / self._safe(document_reference)
        )
        target.mkdir(parents=True, exist_ok=True)

        if table_regions_path is None:
            regions = self._regions_from_extraction(extraction, extraction_path)
            table_regions_path = target / "table_regions.json"
            self._write(table_regions_path, regions)
        else:
            table_regions_path = table_regions_path.resolve()
            regions = self._read(table_regions_path)

        parsed_path = target / "parsed_document.json"
        summary_path = target / "parser_summary.json"
        digest_path = target / "parser_digest.txt"
        review_path = target / "parser_review.json"

        table_result = TableProcessingPipeline().run(
            extraction=extraction, regions=regions
        )
        owned = set(table_result["table_owned_item_ids"])
        repeated = self._repeated_margin_signatures(extraction["pages"])

        events: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        pages_out: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()

        table_by_page = defaultdict(list)
        for table in table_result["tables"]:
            table_by_page[int(table["page_number"])].append(table)

        for page in extraction["pages"]:
            page_no = int(page["page_number"])
            height = float(page.get("height_points") or 1)
            kept = garbage = duplicates = furniture = table_items = 0
            for item in sorted(
                page.get("items", []),
                key=lambda value: int(value.get("reading_order") or 0),
            ):
                item_id = str(item.get("item_id"))
                text = self._normalize(item.get("text"))
                order = int(item.get("reading_order") or 0)
                bbox = self._canonical_bbox(item.get("bbox"), height)
                if item_id in owned:
                    table_items += 1
                    decision = "TABLE_OWNED"
                    reasons = ["accepted_table_region"]
                    # A table region can accidentally absorb the heading of
                    # the next note (common on two-column / tightly packed
                    # pages). Preserve that heading for section construction
                    # even though its text remains table-owned.
                    headings = self._heading_events(item, text)
                    if headings:
                        for heading in headings:
                            events.append(
                                {
                                    "kind": "heading",
                                    "page_number": page_no,
                                    "order": order,
                                    "item_id": item_id,
                                    "text": heading["text"],
                                    "classification": heading["classification"],
                                    "level": heading.get("level"),
                                    "reasons": heading["reasons"]
                                    + ["heading_inside_table_region"],
                                }
                            )
                else:
                    quality, reasons = self._text_quality(text)
                    key = (
                        page_no,
                        text.casefold(),
                        tuple(round(value, 1) for value in bbox) if bbox else None,
                    )
                    if quality == "REJECTED":
                        garbage += 1
                        decision = "REJECTED_GARBAGE"
                    elif self._is_furniture(text, bbox, height, repeated):
                        furniture += 1
                        decision = "PAGE_FURNITURE"
                        reasons.append("repeated_margin")
                    elif key in seen:
                        duplicates += 1
                        decision = "DUPLICATE"
                        reasons.append("same_page_text_and_bbox")
                    else:
                        seen.add(key)
                        decision = "KEEP"
                        headings = self._heading_events(item, text)
                        if headings:
                            for heading in headings:
                                events.append(
                                    {
                                        "kind": "heading",
                                        "page_number": page_no,
                                        "order": order,
                                        "item_id": item_id,
                                        "text": heading["text"],
                                        "classification": heading["classification"],
                                        "level": heading.get("level"),
                                        "reasons": heading["reasons"],
                                    }
                                )
                        else:
                            events.append(
                                {
                                    "kind": "text",
                                    "page_number": page_no,
                                    "order": order,
                                    "item_id": item_id,
                                    "text": text,
                                    "item_type": item.get("item_type"),
                                    "quality": quality,
                                    "reasons": reasons,
                                }
                            )
                        kept += 1
                decisions.append(
                    {
                        "item_id": item_id,
                        "page_number": page_no,
                        "decision": decision,
                        "reasons": reasons,
                    }
                )

            for table in table_by_page.get(page_no, []):
                events.append(
                    {
                        "kind": "table",
                        "page_number": page_no,
                        "order": int(table.get("reading_order_start") or 10**9),
                        "table": table,
                    }
                )
            pages_out.append(
                {
                    "page_number": page_no,
                    "kept_item_count": kept,
                    "garbage_removed": garbage,
                    "duplicate_removed": duplicates,
                    "furniture_removed": furniture,
                    "table_owned_item_count": table_items,
                    "table_ids": [table["table_id"] for table in table_by_page.get(page_no, [])],
                }
            )

        sections, records = self._build_sections(events)
        section_map = {section["section_id"]: section for section in sections}

        for table in table_result["tables"]:
            section_id = table.pop("_section_id", None)
            table["section_id"] = section_id
            table["section_title"] = section_map.get(section_id, {}).get("title")
            table["heading_path"] = section_map.get(section_id, {}).get(
                "heading_path", []
            )
            if section_id:
                section_map[section_id]["table_ids"].append(table["table_id"])

        for section in sections:
            section["record_ids"] = list(dict.fromkeys(section["record_ids"]))
            section["table_ids"] = list(dict.fromkeys(section["table_ids"]))
            section["record_count"] = len(section["record_ids"])
            section["table_count"] = len(section["table_ids"])
            section["section_type"] = "parent" if section["child_count"] else "leaf"

        document = {
            "schema_version": self.SCHEMA_VERSION,
            "parser_version": self.VERSION,
            "source_extraction_path": str(extraction_path),
            "source_table_regions_path": str(table_regions_path),
            "document": extraction.get("document") or {},
            "pages": pages_out,
            "sections": sections,
            "records": records,
            "tables": table_result["tables"],
            "item_decisions": decisions,
            "table_processing": {
                "pipeline_version": table_result["pipeline_version"],
                "failures": table_result["failures"],
            },
            "audit": {
                "source_item_count": sum(len(page.get("items") or []) for page in extraction["pages"]),
                "table_owned_count": len(owned),
                "garbage_removed": sum(
                    decision["decision"] == "REJECTED_GARBAGE"
                    for decision in decisions
                ),
                "duplicate_removed": sum(
                    decision["decision"] == "DUPLICATE" for decision in decisions
                ),
                "furniture_removed": sum(
                    decision["decision"] == "PAGE_FURNITURE" for decision in decisions
                ),
                "section_count": len(sections),
                "table_count": len(table_result["tables"]),
                "table_failure_count": len(table_result["failures"]),
            },
        }
        self._write(parsed_path, document)
        review = {
            "sections": sections,
            "pages": pages_out,
            "tables": [
                {
                    "table_id": table["table_id"],
                    "page": table["page_number"],
                    "section": table.get("section_title"),
                    "quality": table["quality_classification"],
                    "warnings": table.get("review_reasons", []),
                }
                for table in table_result["tables"]
            ],
            "audit": document["audit"],
        }
        self._write(review_path, review)
        digest_path.write_text(self._digest(document), encoding="utf-8")
        accepted = sum(
            record["quality_classification"] == "ACCEPTED" for record in records
        ) + sum(
            table["quality_classification"] == "ACCEPTED"
            for table in table_result["tables"]
        )
        review_count = sum(
            record["quality_classification"] == "REVIEW_REQUIRED"
            for record in records
        ) + sum(
            table["quality_classification"] == "REVIEW_REQUIRED"
            for table in table_result["tables"]
        )
        result = StructuralParsingResult(
            str(extraction_path),
            str(target),
            str(parsed_path),
            str(summary_path),
            str(digest_path),
            len(pages_out),
            len(pages_out),
            0,
            len(sections),
            len(table_result["tables"]),
            accepted,
            review_count,
            document["audit"]["garbage_removed"],
            "REVIEW_REQUIRED" if review_count or table_result["failures"] else "COMPLETED",
        )
        self._write(
            summary_path,
            {
                "parser_version": self.VERSION,
                "elapsed_seconds": round(perf_counter() - started, 3),
                "result": asdict(result),
                "review_path": str(review_path),
                "table_failures": table_result["failures"],
            },
        )
        return result

    def _regions_from_extraction(
        self,
        extraction: dict[str, Any],
        extraction_path: Path,
    ) -> dict[str, Any]:
        regions = [
            region
            for page in extraction["pages"]
            for region in detect_page(page)
        ]
        return {
            "schema_version": "1.0",
            "source_extraction": str(extraction_path),
            "processed_page_count": len(extraction["pages"]),
            "detected_region_count": len(regions),
            "regions": regions,
        }

    def _heading_events(
        self,
        item: dict[str, Any],
        text: str,
    ) -> list[dict[str, Any]] | None:
        is_docling_heading = (
            item.get("item_type") == "heading"
            or item.get("label") in {"section_header", "title", "document_index"}
        )
        if not is_docling_heading and not self._looks_like_paragraph_heading(text):
            return None
        low = text.casefold().strip()
        if (
            low in self.MASTHEADS
            or self.FIELD_LABEL_RE.fullmatch(text)
            or self.PERSON_RE.fullmatch(text)
            or self.CONTENT_LABEL_RE.fullmatch(text)
            or self.DATE_SUBTITLE_RE.match(text)
        ):
            return None

        merged = self.MERGED_CONTINUATION_RE.match(text)
        if merged:
            first = merged.group(1).strip()
            second = merged.group(2).strip()
            return [
                {
                    "text": first,
                    "classification": "CONTINUATION",
                    "level": self._heading_level(first),
                    "reasons": ["merged_continuation_part"],
                },
                {
                    "text": second,
                    "classification": "SECTION",
                    "level": self._heading_level(second),
                    "reasons": ["merged_new_heading_part"],
                },
            ]
        if "(continued)" in low:
            cleaned = self.CONTINUED_RE.sub("", text).strip()
            return [
                {
                    "text": cleaned,
                    "classification": "CONTINUATION",
                    "level": self._heading_level(cleaned),
                    "reasons": ["continued"],
                }
            ]
        words = text.split()
        if len(words) > 18 or len(text) > 180 or self.PAGE_NUMBER_RE.fullmatch(text):
            return None
        level = self._heading_level(text)
        return [
            {
                "text": text,
                "classification": "SECTION" if level == 1 else "SUBSECTION",
                "level": level,
                "reasons": ["docling_heading_validated"],
            }
        ]

    def _looks_like_paragraph_heading(self, text: str) -> bool:
        if not text or len(text) > 180:
            return False
        words = text.split()
        if len(words) > 18 or text.endswith((".", ":", ";")):
            return False
        if self.CONTINUED_RE.search(text):
            return True
        return bool(self.NUMBERED_RE.match(text))

    def _heading_key(self, text: str) -> str:
        cleaned = self.CONTINUED_RE.sub("", text).strip().casefold()
        cleaned = re.sub(r"^\(?([a-z0-9]+)[.)]\s*", r"\1 ", cleaned)
        return " ".join(cleaned.split())

    def _heading_level(self, text: str) -> int:
        cleaned = self.CONTINUED_RE.sub("", text).strip()
        if self.NUMBERED_RE.match(cleaned):
            return 1
        letters = [char for char in cleaned if char.isalpha()]
        uppercase = sum(char.isupper() for char in letters) / max(1, len(letters))
        if uppercase > 0.78 and len(cleaned.split()) <= 14:
            return 1
        return 2

    def _build_sections(
        self,
        events: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        events = sorted(
            events,
            key=lambda event: (
                event["page_number"],
                event["order"],
                0 if event["kind"] == "heading" else 1,
            ),
        )
        sections: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []
        section_map: dict[str, dict[str, Any]] = {}
        active: dict[int, str] = {}
        known: dict[str, list[str]] = defaultdict(list)
        current: str | None = None
        buffers: dict[str, list[dict[str, Any]]] = defaultdict(list)

        def touch(section_id: str, page_number: int) -> None:
            section = section_map[section_id]
            section["page_end"] = max(int(section["page_end"]), page_number)
            parent_id = section["parent_section_id"]
            while parent_id and parent_id in section_map:
                parent = section_map[parent_id]
                parent["page_end"] = max(int(parent["page_end"]), page_number)
                parent_id = parent["parent_section_id"]

        def create(
            text: str,
            level: int,
            page_number: int,
            item_id: str | None,
            reasons: list[str],
        ) -> str:
            nonlocal current
            parent = next(
                (active[value] for value in range(level - 1, 0, -1) if value in active),
                None,
            )
            section_id = f"SEC-{len(sections) + 1:05d}"
            parent_path = (
                section_map[parent]["heading_path"] if parent else []
            )
            section = {
                "section_id": section_id,
                "title": text,
                "heading_level": level,
                "parent_section_id": parent,
                "heading_path": parent_path + [text],
                "page_start": page_number,
                "page_end": page_number,
                "heading_item_id": item_id,
                "heading_reasons": reasons,
                "record_ids": [],
                "table_ids": [],
                "child_count": 0,
                "_continuation_pages": [],
            }
            sections.append(section)
            section_map[section_id] = section
            if parent:
                section_map[parent]["child_count"] += 1
                touch(parent, page_number)
            known[self._heading_key(text)].append(section_id)
            active[level] = section_id
            for stale in [value for value in active if value > level]:
                del active[stale]
            current = section_id
            return section_id

        def ensure_introduction(page_number: int) -> str:
            if sections:
                return sections[-1]["section_id"]
            return create(
                "Document introduction",
                1,
                page_number,
                None,
                ["fallback_before_first_heading"],
            )

        for event in events:
            page_number = int(event["page_number"])
            if event["kind"] == "heading":
                key = self._heading_key(event["text"])
                if event["classification"] == "CONTINUATION":
                    if known.get(key):
                        current = known[key][-1]
                        section = section_map[current]
                        if not section.get("_continuation_pages"):
                            section["_continuation_pages"] = []
                        section["_continuation_pages"].append(page_number)
                        touch(current, page_number)
                        continue
                    level = int(event.get("level") or self._heading_level(event["text"]))
                    reasons = list(event["reasons"]) + ["continued_without_prior_record"]
                    current = create(
                        event["text"],
                        level,
                        page_number,
                        event.get("item_id"),
                        reasons,
                    )
                    continue
                level = int(event.get("level") or self._heading_level(event["text"]))
                current = create(
                    event["text"],
                    level,
                    page_number,
                    event.get("item_id"),
                    list(event["reasons"]),
                )
            elif event["kind"] == "table":
                if current is None:
                    current = ensure_introduction(page_number)
                event["table"]["_section_id"] = current
                touch(current, page_number)
            else:
                if current is None:
                    current = ensure_introduction(page_number)
                buffers[current].append(event)
                touch(current, page_number)

        for section_id, items in buffers.items():
            by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for item in items:
                by_page[int(item["page_number"])].append(item)
            for page_number, page_items in sorted(by_page.items()):
                text = "\n\n".join(
                    item["text"] for item in page_items if item["text"]
                )
                if not text:
                    continue
                record_id = f"{section_id}-P{page_number:04d}"
                section = section_map[section_id]
                records.append(
                    {
                        "record_id": record_id,
                        "record_type": "SECTION_TEXT",
                        "section_id": section_id,
                        "section_title": section["title"],
                        "heading_path": section["heading_path"],
                        "page_start": page_number,
                        "page_end": page_number,
                        "content_text": text,
                        "source_item_ids": [
                            item["item_id"] for item in page_items
                        ],
                        "quality_classification": (
                            "REVIEW_REQUIRED"
                            if any(item["quality"] == "REVIEW_REQUIRED" for item in page_items)
                            else "ACCEPTED"
                        ),
                        "warnings": sorted(
                            {
                                reason
                                for item in page_items
                                for reason in item["reasons"]
                            }
                        ),
                        "source_reference": (
                            f"page {page_number}, section {section['title']}"
                        ),
                    }
                )
                section["record_ids"].append(record_id)

        # Parent page ranges must cover all of their children and records.
        for section in reversed(sections):
            parent_id = section["parent_section_id"]
            if parent_id and parent_id in section_map:
                parent = section_map[parent_id]
                parent["page_end"] = max(
                    int(parent["page_end"]), int(section["page_end"])
                )
            section.pop("_continuation_pages", None)

        return sections, records

    @staticmethod
    def _text_quality(text: str) -> tuple[str, list[str]]:
        if not text:
            return "REJECTED", ["empty"]
        chars = [char for char in text if not char.isspace()]
        alpha = sum(char.isalpha() for char in chars) / max(1, len(chars))
        symbols = sum(
            char in LightweightParsingPipelineV8.GARBAGE_SYMBOLS for char in chars
        ) / max(1, len(chars))
        words = re.findall(r"[A-Za-z]{2,}", html.unescape(text))
        if (symbols >= 0.18 and alpha < 0.55) or (
            len(text) > 20 and not words
        ):
            return "REJECTED", ["symbol_heavy"]
        if symbols >= 0.08 or alpha < 0.30:
            return "REVIEW_REQUIRED", ["uncertain_text_quality"]
        return "ACCEPTED", []

    def _repeated_margin_signatures(
        self,
        pages: list[dict[str, Any]],
    ) -> set[str]:
        counts: Counter[str] = Counter()
        for page in pages:
            height = float(page.get("height_points") or 1)
            for item in page.get("items") or []:
                box = self._canonical_bbox(item.get("bbox"), height)
                text = self._normalize(item.get("text")).casefold()
                if (
                    box
                    and text
                    and len(text) <= 160
                    and (box[1] <= height * 0.055 or box[3] >= height * 0.945)
                ):
                    counts[text] += 1
        return {text for text, count in counts.items() if count >= 3}

    @staticmethod
    def _is_furniture(
        text: str,
        bbox: list[float] | None,
        height: float,
        repeated: set[str],
    ) -> bool:
        return bool(
            bbox
            and text.casefold() in repeated
            and (bbox[1] <= height * 0.055 or bbox[3] >= height * 0.945)
        )

    @staticmethod
    def _canonical_bbox(
        bbox: dict[str, Any] | None,
        height: float,
    ) -> list[float] | None:
        if not bbox:
            return None
        left = float(bbox.get("left", 0))
        right = float(bbox.get("right", 0))
        top = float(bbox.get("top", 0))
        bottom = float(bbox.get("bottom", 0))
        origin = str(bbox.get("coord_origin", "")).upper()
        if "BOTTOMLEFT" in origin:
            return [left, height - max(top, bottom), right, height - min(top, bottom)]
        return [left, min(top, bottom), right, max(top, bottom)]

    @staticmethod
    def _normalize(value: Any) -> str:
        return re.sub(
            r"\s+",
            " ",
            html.unescape(str(value or "")).replace("\u00ad", ""),
        ).strip()

    @staticmethod
    def _safe(value: str) -> str:
        text = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._")
        if not text:
            raise LightweightParsingError("Invalid reference")
        return text[:120]

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write(path: Path, value: Any) -> None:
        path.write_text(
            json.dumps(value, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _digest(document: dict[str, Any]) -> str:
        return (
            "\n".join(
                [
                    "LIGHTWEIGHT PARSER V8.1",
                    "=" * 72,
                    f"Sections: {len(document['sections'])}",
                    f"Narrative records: {len(document['records'])}",
                    f"Tables: {len(document['tables'])}",
                    f"Garbage removed: {document['audit']['garbage_removed']}",
                    f"Duplicates removed: {document['audit']['duplicate_removed']}",
                    f"Table-owned items removed: {document['audit']['table_owned_count']}",
                    "",
                    *[
                        f"{section['section_id']} | L{section['heading_level']} | "
                        f"{' > '.join(section['heading_path'])}"
                        for section in document["sections"]
                    ],
                ]
            )
            + "\n"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse validated Docling extraction into section-grounded records."
    )
    parser.add_argument("--extraction", required=True, type=Path)
    parser.add_argument("--table-regions", type=Path)
    parser.add_argument("--output", default="parsed-v8-output", type=Path)
    parser.add_argument("--application", default="TEST")
    parser.add_argument("--document", default="DOC")
    args = parser.parse_args()
    result = LightweightParsingPipelineV8(parsed_root=args.output).parse(
        extraction_path=args.extraction,
        table_regions_path=args.table_regions,
        application_reference=args.application,
        document_reference=args.document,
    )
    print(json.dumps(asdict(result), indent=2))
    print("Inspect:", result.parsed_document_path)


if __name__ == "__main__":
    main()
