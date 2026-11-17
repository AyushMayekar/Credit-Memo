from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.services.credit_memo_batch_definitions import BATCHES


class CreditMemoBatchCombiner:
    """Combine small batch outputs into the section content expected by the assembler."""

    def combine(
        self, batch_results: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        grouped = defaultdict(list)
        for batch in BATCHES:
            grouped[batch.section_key].append(batch_results[batch.key])
        return {section: self._merge(parts) for section, parts in grouped.items()}

    def _merge(self, parts):
        available = [part for part in parts if part.get("status") == "available"]
        summaries = [part.get("summary") for part in available if part.get("summary")]
        facts = self._dedupe(
            [item for part in parts for item in part.get("facts", [])],
            ("label", "period", "value"),
        )[:8]
        observations = self._dedupe(
            [item for part in parts for item in part.get("observations", [])],
            ("key", "title"),
        )[:4]
        items = self._dedupe(
            [item for part in parts for item in part.get("items", [])],
            ("item_id", "title"),
        )[:6]
        source_ids = list(
            dict.fromkeys(sid for part in parts for sid in part.get("source_ids", []))
        )[:8]
        caveats = list(
            dict.fromkeys(str(x) for part in parts for x in part.get("caveats", []))
        )[:3]
        return {
            "status": (
                "available"
                if available
                else (
                    "pending_review"
                    if any(p.get("status") == "pending_review" for p in parts)
                    else "not_disclosed"
                )
            ),
            "summary": " ".join(summaries) if summaries else None,
            "facts": facts,
            "observations": observations,
            "items": items,
            "caveats": caveats,
            "source_ids": source_ids,
        }

    @staticmethod
    def _dedupe(items, keys):
        output = []
        seen = set()
        for item in items:
            identity = tuple(str(item.get(key, "")).casefold() for key in keys)
            if identity in seen:
                continue
            seen.add(identity)
            output.append(item)
        return output
