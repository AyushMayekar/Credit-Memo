from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from time import perf_counter
from typing import Any

import pymupdf
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption


class StandaloneExtractionError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class StandaloneExtractionResult:
    source_pdf: str
    extraction_path: str
    review_path: str
    digest_path: str
    summary_path: str
    page_count: int
    processed_pages: list[int]
    item_count: int
    heading_count: int
    elapsed_seconds: float
    status: str


class StandaloneHybridExtractorV4:
    """Lossless Docling text/layout extraction for the reconstruction parser.

    This extractor deliberately performs **no table detection**. Tables are not
    an extraction concern any more. The parser reconstructs table regions from
    the Docling text items and their geometry, which keeps one source of truth
    and avoids mixing pdfplumber table heuristics with Docling layout data.

    The class name is kept for compatibility with existing entrypoints. New
    code should use :class:`StandaloneDoclingExtractorV5`.
    """

    VERSION = "standalone-docling-text-v5"
    SCHEMA_VERSION = "5.0"

    def __init__(self, *, output_root: Path, artifacts_path: Path) -> None:
        self.output_root = output_root.resolve()
        self.artifacts_path = artifacts_path.resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self._validate_artifacts()

    def extract(
        self,
        *,
        pdf_path: Path,
        application_reference: str,
        document_reference: str,
        document_name: str,
        period_type: str,
        period_end: date,
        period_label: str,
        pages: list[int] | None = None,
    ) -> StandaloneExtractionResult:
        started = perf_counter()
        pdf_path = pdf_path.resolve()
        self._validate_pdf(pdf_path)
        with pymupdf.open(pdf_path) as source:
            page_count = source.page_count
        selected = self._validate_pages(pages, page_count)
        target = self.output_root / self._safe(application_reference) / self._safe(document_reference)
        target.mkdir(parents=True, exist_ok=True)
        extraction_path = target / "extraction.json"
        review_path = target / "extraction_review.json"
        digest_path = target / "extraction_digest.txt"
        summary_path = target / "extraction_summary.json"

        temporary = None
        try:
            docling_pdf, page_map, temporary = self._make_subset(pdf_path, selected)
            conversion = self._build_converter().convert(str(docling_pdf))
            items = self._docling_items(conversion.document, page_map)
            page_payloads = self._docling_pages(conversion.document, page_map, items)
        except Exception as exc:
            raise StandaloneExtractionError(
                f"Extraction failed for {pdf_path.name}: {exc}"
            ) from exc
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "extraction_method": self.VERSION,
            "docling_version": importlib.metadata.version("docling"),
            "configuration": {
                "docling_ocr": False,
                "docling_table_structure": False,
                "docling_remote_services": False,
                "lossless_docling_items": True,
                "table_detection": False,
                "processed_pages": selected,
            },
            "document": {
                "application_reference": application_reference,
                "document_reference": document_reference,
                "source_pdf": str(pdf_path),
                "filename": pdf_path.name,
                "source_sha256": self._sha256(pdf_path),
                "source_page_count": page_count,
                "document_name": document_name,
                "period_type": period_type,
                "period_end": period_end.isoformat(),
                "period_label": period_label,
                "metadata_source": "user_confirmed",
            },
            "pages": page_payloads,
        }
        elapsed = round(perf_counter() - started, 3)
        review = self._review(payload, elapsed)
        all_items = [item for page in page_payloads for item in page["items"]]
        summary = {
            "schema_version": self.SCHEMA_VERSION,
            "extraction_method": self.VERSION,
            "processed_pages": selected,
            "source_page_count": page_count,
            "item_count": len(all_items),
            "heading_count": sum(item["item_type"] == "heading" for item in all_items),
            "paragraph_count": sum(item["item_type"] == "paragraph" for item in all_items),
            "elapsed_seconds": elapsed,
            "extraction_path": str(extraction_path),
            "review_path": str(review_path),
            "digest_path": str(digest_path),
            "status": "READY_FOR_INSPECTION",
        }
        self._write_json(extraction_path, payload)
        self._write_json(review_path, review)
        self._write_json(summary_path, summary)
        digest_path.write_text(self._digest(review), encoding="utf-8")
        return StandaloneExtractionResult(
            str(pdf_path),
            str(extraction_path),
            str(review_path),
            str(digest_path),
            str(summary_path),
            page_count,
            selected,
            summary["item_count"],
            summary["heading_count"],
            elapsed,
            "READY_FOR_INSPECTION",
        )

    def _build_converter(self) -> DocumentConverter:
        options = PdfPipelineOptions(
            artifacts_path=self.artifacts_path,
            do_ocr=False,
            do_table_structure=False,
            enable_remote_services=False,
        )
        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )

    @staticmethod
    def _make_subset(pdf_path: Path, selected: list[int]):
        source = subset = None
        temporary = None
        try:
            source = pymupdf.open(pdf_path)
            all_pages = list(range(1, source.page_count + 1))
            if selected == all_pages:
                return pdf_path, {p: p for p in all_pages}, None
            fd, name = tempfile.mkstemp(prefix="docling_subset_", suffix=".pdf")
            os.close(fd)
            temporary = Path(name)
            temporary.unlink(missing_ok=True)
            subset = pymupdf.open()
            page_map = {}
            for local, original in enumerate(selected, 1):
                subset.insert_pdf(source, from_page=original - 1, to_page=original - 1)
                page_map[local] = original
            subset.save(temporary, garbage=4, deflate=True, clean=True)
            return temporary, page_map, temporary
        finally:
            if subset is not None:
                subset.close()
            if source is not None:
                source.close()

    def _docling_items(self, document: Any, page_map: dict[int, int]):
        """Return every non-empty Docling text item, including table-region text.

        Docling table *objects* are not used. If Docling emits a table-labelled
        item with text while table structure is disabled, that text is retained
        as ordinary paragraph text so the parser can reconstruct it from raw
        geometry rather than losing it.
        """
        output = {page: [] for page in page_map.values()}
        sequence = 0
        for item, level in document.iterate_items():
            label = str(getattr(item, "label", "") or "").split(".")[-1].lower()
            text = self._clean(getattr(item, "text", ""))
            if not text:
                continue
            for prov in list(getattr(item, "prov", None) or []):
                page = page_map.get(int(getattr(prov, "page_no", 0) or 0))
                if page is None:
                    continue
                sequence += 1
                output[page].append(
                    {
                        "item_id": f"P{page:04d}-B{sequence:05d}",
                        "item_type": self._item_type(label),
                        "label": label,
                        "hierarchy_level": level if isinstance(level, int) else None,
                        "text": text,
                        "reading_order": sequence,
                        "page_number": page,
                        "bbox": self._bbox_dict(getattr(prov, "bbox", None)),
                    }
                )
        return output

    def _docling_pages(
        self,
        document: Any,
        page_map: dict[int, int],
        items: dict[int, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        page_nodes = getattr(document, "pages", {}) or {}
        for local_page, original_page in sorted(page_map.items()):
            page_items = sorted(
                items.get(original_page, []),
                key=lambda item: int(item.get("reading_order") or 0),
            )
            node = self._lookup_page(page_nodes, local_page)
            width, height = self._page_size(node, page_items)
            pages.append(
                {
                    "page_number": original_page,
                    "width_points": round(width, 3),
                    "height_points": round(height, 3),
                    "items": page_items,
                    "page_text": "\n".join(item["text"] for item in page_items),
                    "item_count": len(page_items),
                    "warnings": [],
                }
            )
        return pages

    @staticmethod
    def _lookup_page(pages: Any, page_number: int) -> Any:
        if not pages:
            return None
        try:
            if page_number in pages:
                return pages[page_number]
        except TypeError:
            pass
        for key, value in pages.items():
            raw = getattr(key, "value", key)
            try:
                if int(raw) == page_number:
                    return value
            except (TypeError, ValueError):
                continue
        return None

    @classmethod
    def _page_size(cls, page: Any, items: list[dict[str, Any]]) -> tuple[float, float]:
        for owner in (getattr(page, "size", None), page):
            if owner is None:
                continue
            width = getattr(owner, "width", None)
            height = getattr(owner, "height", None)
            if width and height:
                return float(width), float(height)
        # Last-resort geometry fallback. This is only used when Docling does not
        # expose a page size; the detector works in relative coordinates.
        width = max(
            (
                float((item.get("bbox") or {}).get("right") or 0)
                for item in items
            ),
            default=0.0,
        )
        height = max(
            (
                max(
                    float((item.get("bbox") or {}).get("top") or 0),
                    float((item.get("bbox") or {}).get("bottom") or 0),
                )
                for item in items
            ),
            default=0.0,
        )
        return max(width, 1.0), max(height, 1.0)

    def _review(self, payload: dict[str, Any], elapsed: float) -> dict[str, Any]:
        pages = []
        for page in payload["pages"]:
            pages.append(
                {
                    "page_number": page["page_number"],
                    "headings": [
                        item["text"]
                        for item in page["items"]
                        if item["item_type"] == "heading"
                    ],
                    "paragraph_previews": [
                        self._clip(item["text"], 220)
                        for item in page["items"]
                        if item["item_type"] == "paragraph"
                    ][:5],
                    "suspected_garbage_items": sum(
                        self._symbol_heavy(item["text"]) for item in page["items"]
                    ),
                    "item_count": len(page["items"]),
                }
            )
        return {
            "schema_version": "5.0-review",
            "document": payload["document"],
            "summary": {
                "processed_pages": len(pages),
                "items": sum(page["item_count"] for page in pages),
                "headings": sum(len(page["headings"]) for page in pages),
                "elapsed_seconds": elapsed,
            },
            "pages": pages,
        }

    @staticmethod
    def _digest(review: dict[str, Any]) -> str:
        summary = review["summary"]
        lines = [
            "STANDALONE DOCLING TEXT EXTRACTION V5",
            "=" * 88,
            f"Document: {review['document'].get('filename')}",
            f"Pages: {summary['processed_pages']} | Items: {summary['items']} | Headings: {summary['headings']}",
        ]
        for page in review["pages"]:
            lines += ["", "-" * 88, f"PAGE {page['page_number']}"]
            lines += [f"H: {value}" for value in page["headings"]]
            lines += [f"P: {value}" for value in page["paragraph_previews"]]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _clean(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").replace("\u00ad", "")).strip()

    @staticmethod
    def _symbol_heavy(text: str) -> bool:
        return bool(
            text
            and sum(c in "!@#=<>^_`{|}~" for c in text) / max(1, len(text)) >= 0.15
        )

    @staticmethod
    def _clip(value: Any, n: int) -> str:
        value = re.sub(r"\s+", " ", str(value or "")).strip()
        return value if len(value) <= n else value[: n - 3] + "..."

    def _validate_artifacts(self) -> None:
        required = (
            self.artifacts_path
            / "docling-project--docling-layout-heron"
            / "model.safetensors"
        )
        if not required.exists():
            raise StandaloneExtractionError(
                f"Missing local Docling layout model: {required}"
            )

    @staticmethod
    def _validate_pdf(path: Path) -> None:
        if not path.is_file() or path.suffix.lower() != ".pdf":
            raise StandaloneExtractionError(f"PDF not found or invalid: {path}")
        with path.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise StandaloneExtractionError("Invalid PDF signature")

    @staticmethod
    def _validate_pages(pages: list[int] | None, count: int) -> list[int]:
        if not pages:
            return list(range(1, count + 1))
        selected = sorted(set(map(int, pages)))
        invalid = [page for page in selected if page < 1 or page > count]
        if invalid:
            raise StandaloneExtractionError(f"Invalid pages {invalid}; PDF has {count}")
        return selected

    @staticmethod
    def _safe(value: str) -> str:
        text = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._")
        if not text:
            raise StandaloneExtractionError("Invalid reference")
        return text[:120]

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _bbox_dict(bbox: Any) -> dict[str, Any]:
        if bbox is None:
            return {}
        return {
            "left": float(getattr(bbox, "l", getattr(bbox, "left", 0))),
            "top": float(getattr(bbox, "t", getattr(bbox, "top", 0))),
            "right": float(getattr(bbox, "r", getattr(bbox, "right", 0))),
            "bottom": float(getattr(bbox, "b", getattr(bbox, "bottom", 0))),
            "coord_origin": str(getattr(bbox, "coord_origin", "unknown")),
        }

    @staticmethod
    def _item_type(label: str) -> str:
        if label in {"section_header", "title", "document_index"}:
            return "heading"
        if label == "list_item":
            return "list_item"
        if label == "footnote":
            return "footnote"
        if label in {"page_header", "page_footer"}:
            return label
        return "paragraph"


# New, clearer name. Keep the old import path working for existing callers.
StandaloneDoclingExtractorV5 = StandaloneHybridExtractorV4


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone Docling text extractor v5")
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--artifacts", default=Path("docling_models"), type=Path)
    parser.add_argument("--output", default=Path("extraction-v5-output"), type=Path)
    parser.add_argument("--pages", nargs="*", type=int)
    parser.add_argument("--page-range", nargs=2, type=int)
    parser.add_argument("--application", default="TEST")
    parser.add_argument("--document", default="DOC")
    parser.add_argument("--document-name", default="Test document")
    parser.add_argument("--period-type", default="annual")
    parser.add_argument("--period-end", default="2024-04-30")
    parser.add_argument("--period-label", default="FY2024")
    args = parser.parse_args()
    pages = args.pages
    if args.page_range:
        start, end = args.page_range
        if start > end:
            parser.error("page range start must be <= end")
        pages = list(range(start, end + 1))
    service = StandaloneHybridExtractorV4(
        output_root=args.output,
        artifacts_path=args.artifacts,
    )
    result = service.extract(
        pdf_path=args.pdf,
        application_reference=args.application,
        document_reference=args.document,
        document_name=args.document_name,
        period_type=args.period_type,
        period_end=date.fromisoformat(args.period_end),
        period_label=args.period_label,
        pages=pages,
    )
    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()
