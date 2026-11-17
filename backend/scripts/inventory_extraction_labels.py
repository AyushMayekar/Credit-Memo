from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def bbox_position(item: dict[str, Any], page_height: float | None) -> str:
    bbox = item.get("bbox") or {}
    if not page_height:
        return "unknown"

    top = bbox.get("top")
    bottom = bbox.get("bottom")
    origin = str(bbox.get("coord_origin", ""))
    if top is None or bottom is None:
        return "unknown"

    # Docling output in this extractor uses bottom-left coordinates.
    if "BOTTOMLEFT" in origin.upper():
        upper_edge = page_height - max(float(top), float(bottom))
        lower_edge = page_height - min(float(top), float(bottom))
    else:
        upper_edge = min(float(top), float(bottom))
        lower_edge = max(float(top), float(bottom))

    center = (upper_edge + lower_edge) / 2
    ratio = center / page_height
    if ratio <= 0.15:
        return "top_margin"
    if ratio >= 0.85:
        return "bottom_margin"
    return "body"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inventory Docling labels from an extractor extraction.json file."
    )
    parser.add_argument("--input", required=True, help="Path to extraction.json")
    parser.add_argument(
        "--output",
        default="docling_label_inventory.json",
        help="Output inventory JSON path",
    )
    parser.add_argument(
        "--samples-per-label",
        type=int,
        default=30,
        help="Maximum unique examples retained for each raw label",
    )
    args = parser.parse_args()

    extraction_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    extraction = load_json(extraction_path)

    label_counts: Counter[str] = Counter()
    item_type_counts: Counter[str] = Counter()
    label_pages: dict[str, set[int]] = defaultdict(set)
    label_item_types: dict[str, Counter[str]] = defaultdict(Counter)
    label_positions: dict[str, Counter[str]] = defaultdict(Counter)
    label_levels: dict[str, Counter[str]] = defaultdict(Counter)
    label_samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_samples: dict[str, set[str]] = defaultdict(set)
    repeated_text: dict[str, dict[str, Any]] = {}
    text_occurrences: dict[str, list[dict[str, Any]]] = defaultdict(list)

    pages = extraction.get("pages", [])
    for page in pages:
        page_number = int(page.get("page_number", 0))
        page_height = page.get("height_points")

        for item in page.get("items", []):
            raw_label = str(item.get("label") or "<missing>")
            item_type = str(item.get("item_type") or "<missing>")
            text = str(item.get("text") or "").strip()
            position = bbox_position(item, float(page_height) if page_height else None)
            hierarchy_level = item.get("hierarchy_level")

            label_counts[raw_label] += 1
            item_type_counts[item_type] += 1
            label_pages[raw_label].add(page_number)
            label_item_types[raw_label][item_type] += 1
            label_positions[raw_label][position] += 1
            if hierarchy_level is not None:
                label_levels[raw_label][str(hierarchy_level)] += 1

            if text and text not in seen_samples[raw_label]:
                if len(label_samples[raw_label]) < args.samples_per_label:
                    label_samples[raw_label].append(
                        {
                            "text": text,
                            "page_number": page_number,
                            "item_id": item.get("item_id"),
                            "item_type": item_type,
                            "hierarchy_level": hierarchy_level,
                            "position": position,
                            "bbox": item.get("bbox"),
                        }
                    )
                seen_samples[raw_label].add(text)

            normalized_text = " ".join(text.casefold().split())
            if normalized_text:
                text_occurrences[normalized_text].append(
                    {
                        "text": text,
                        "page_number": page_number,
                        "raw_label": raw_label,
                        "item_type": item_type,
                        "position": position,
                    }
                )

    for normalized_text, occurrences in text_occurrences.items():
        occurrence_pages = sorted({o["page_number"] for o in occurrences})
        if len(occurrence_pages) < 2:
            continue
        positions = Counter(o["position"] for o in occurrences)
        repeated_text[normalized_text] = {
            "display_text": occurrences[0]["text"],
            "occurrence_count": len(occurrences),
            "page_count": len(occurrence_pages),
            "pages": occurrence_pages,
            "labels": dict(sorted(Counter(o["raw_label"] for o in occurrences).items())),
            "item_types": dict(sorted(Counter(o["item_type"] for o in occurrences).items())),
            "positions": dict(sorted(positions.items())),
            "likely_page_furniture": (
                len(occurrence_pages) >= 3
                and (positions["top_margin"] + positions["bottom_margin"])
                / len(occurrences)
                >= 0.8
            ),
        }

    labels = {}
    for label in sorted(label_counts):
        labels[label] = {
            "count": label_counts[label],
            "page_count": len(label_pages[label]),
            "pages": sorted(label_pages[label]),
            "mapped_item_types": dict(sorted(label_item_types[label].items())),
            "hierarchy_levels": dict(sorted(label_levels[label].items())),
            "positions": dict(sorted(label_positions[label].items())),
            "samples": label_samples[label],
        }

    inventory = {
        "inventory_description": (
            "Direct inventory of raw item labels already present in extraction.json. "
            "No section-opening decisions are made by this script."
        ),
        "source_extraction": str(extraction_path),
        "extraction_method": extraction.get("extraction_method"),
        "schema_version": extraction.get("schema_version"),
        "processed_page_count": len(pages),
        "processed_pages": [page.get("page_number") for page in pages],
        "total_items": sum(label_counts.values()),
        "raw_label_counts": dict(sorted(label_counts.items())),
        "mapped_item_type_counts": dict(sorted(item_type_counts.items())),
        "labels": labels,
        "repeated_text_candidates": sorted(
            repeated_text.values(),
            key=lambda value: (-value["page_count"], value["display_text"].casefold()),
        ),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(inventory, handle, indent=2, ensure_ascii=False)

    print(
        json.dumps(
            {
                "status": "LABEL_INVENTORY_CREATED",
                "source": str(extraction_path),
                "output": str(output_path),
                "processed_page_count": len(pages),
                "total_items": sum(label_counts.values()),
                "raw_label_counts": dict(sorted(label_counts.items())),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
