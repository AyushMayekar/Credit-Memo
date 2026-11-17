from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from jsonschema import Draft202012Validator

from app.ai.llm import get_llm
from app.ai.prompts.credit_memo_prompts import (
    build_batch_messages,
    build_recommendation_messages,
)
from app.ai.retrieval.faiss_retriever import ApplicationFaissRetriever
from app.ai.retrieval.json_utils import LlmJsonError, parse_json_object
from app.ai.retrieval.section_retriever import MemoBatchRetriever, RetrievalRequest
from app.core.config import settings
from app.db.session import SessionLocal
from app.services.credit_memo_batch_definitions import BATCHES, MemoBatch


class CreditMemoExtractionService:
    MAX_CONCURRENCY = 3

    def __init__(self, session_factory: Callable = SessionLocal) -> None:
        self.session_factory = session_factory

    def extract_all(
        self,
        *,
        request: RetrievalRequest,
        application_facts: dict[str, Any],
    ):
        results: dict[str, dict[str, Any]] = {}
        sources: dict[str, dict[str, Any]] = {}
        audit: list[dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=self.MAX_CONCURRENCY) as pool:
            futures = {
                pool.submit(self._run_batch, request, application_facts, batch): batch
                for batch in BATCHES
            }
            for future in as_completed(futures):
                batch = futures[future]
                result, batch_sources, row = future.result()
                results[batch.key] = result
                sources.update(batch_sources)
                audit.append(row)

        order = {batch.key: index for index, batch in enumerate(BATCHES)}
        audit.sort(key=lambda row: order[row["batch"]])
        return results, sources, audit

    def _run_batch(
        self,
        request: RetrievalRequest,
        application_facts: dict[str, Any],
        batch: MemoBatch,
    ):
        with self.session_factory() as session:
            index_path = (
                settings.resolve_path(settings.faiss_dir)
                / f"{settings.faiss_index_name}.faiss"
            )
            retriever = MemoBatchRetriever(
                ApplicationFaissRetriever(session, index_path)
            )
            raw, packet = retriever.retrieve(request=request, batch=batch)
            sources = {
                retriever.source_id(item): self._source(
                    session,
                    item,
                    retriever.source_id(item),
                )
                for item in raw
            }

        if not packet:
            return (
                self._normalize(
                    {
                        "status": "not_disclosed",
                        "summary": None,
                        "caveats": ["No relevant evidence was retrieved."],
                        "source_ids": [],
                    }
                ),
                sources,
                {
                    "batch": batch.key,
                    "evidence": 0,
                    "attempts": 0,
                    "retrieval_context": "child_to_parent_v2",
                },
            )

        messages, contract, aliases = build_batch_messages(
            batch=batch,
            application_facts=application_facts,
            evidence=packet,
        )
        result, response_characters, attempts = self._invoke_json_messages(
            messages,
            max_tokens=batch.max_output_tokens,
            label=f"Memo batch '{batch.key}'",
        )
        result = self._normalize_generated_text(result, batch=batch)

        errors = [
            (
                f"{'/'.join(str(value) for value in error.absolute_path) or '$'}: "
                f"{error.message}"
            )
            for error in Draft202012Validator(contract).iter_errors(result)
        ]
        if errors:
            raise ValueError(
                f"Memo batch '{batch.key}' returned invalid output: "
                f"{'; '.join(errors[:5])}"
            )

        result = self._expand_aliases(result, aliases)
        result = self._normalize(result)
        return (
            result,
            sources,
            {
                "batch": batch.key,
                "section": batch.section_key,
                "kind": batch.output.kind,
                "evidence": len(packet),
                "attempts": attempts,
                "output_characters": response_characters,
                "retrieval_context": "child_to_parent_v2",
                "parent_context_ids": [
                    item.get("parent_content_id") for item in packet
                ],
            },
        )

    def recommend(self, *, digest, allowed_source_ids):
        result, _, _ = self._invoke_json_messages(
            build_recommendation_messages(digest=digest),
            max_tokens=1400,
            label="Recommendation",
        )
        return self._filter_sources(result, allowed_source_ids)

    @staticmethod
    def _invoke_json_messages(
        messages: list[dict],
        *,
        max_tokens: int,
        label: str,
    ) -> tuple[dict[str, Any], int, int]:
        llm = get_llm()
        response = llm.chat_response(
            messages,
            temperature=0,
            max_tokens=max_tokens,
        )
        if response.finish_reason in {"length", "max_tokens"}:
            raise ValueError(f"{label} exceeded its {max_tokens}-token output limit.")

        try:
            return parse_json_object(response.content), len(response.content), 1
        except LlmJsonError:
            repair_messages = [
                {
                    "role": "system",
                    "content": (
                        "Repair the supplied response into exactly one valid JSON "
                        "object. Preserve meaning, do not add facts, and return no "
                        "Markdown or commentary."
                    ),
                },
                {
                    "role": "user",
                    "content": response.content[:12000],
                },
            ]
            repaired = llm.chat_response(
                repair_messages,
                temperature=0,
                max_tokens=max_tokens,
            )
            if repaired.finish_reason in {"length", "max_tokens"}:
                raise ValueError(f"{label} JSON repair was truncated.")
            return parse_json_object(repaired.content), len(repaired.content), 2

    @staticmethod
    def _expand_aliases(value, aliases):
        if isinstance(value, dict):
            return {
                key: (
                    [aliases[item] for item in item_value if item in aliases]
                    if key == "source_ids" and isinstance(item_value, list)
                    else CreditMemoExtractionService._expand_aliases(
                        item_value,
                        aliases,
                    )
                )
                for key, item_value in value.items()
            }
        if isinstance(value, list):
            return [
                CreditMemoExtractionService._expand_aliases(item, aliases)
                for item in value
            ]
        return value

    @staticmethod
    def _normalize(result):
        output = dict(result)
        output.setdefault("facts", [])
        output.setdefault("observations", [])
        output.setdefault("items", [])
        output.setdefault("caveats", [])
        output.setdefault("source_ids", [])
        return output

    @staticmethod
    def _filter_sources(value, allowed):
        if isinstance(value, dict):
            return {
                key: (
                    [item for item in item_value if item in allowed]
                    if key == "source_ids" and isinstance(item_value, list)
                    else CreditMemoExtractionService._filter_sources(
                        item_value,
                        allowed,
                    )
                )
                for key, item_value in value.items()
            }
        if isinstance(value, list):
            return [
                CreditMemoExtractionService._filter_sources(item, allowed)
                for item in value
            ]
        return value

    @staticmethod
    def _source(session, item, source_id):
        from app.db.models import Document, DocumentContent

        content = session.get(DocumentContent, item.content_id)
        document = session.get(Document, content.document_id) if content else None
        return {
            "source_id": source_id,
            "document_id": content.document_id if content else None,
            "document_name": (
                document.original_filename if document else "Unknown document"
            ),
            "document_type": (
                (document.document_type or "other").lower() if document else "other"
            ),
            "reporting_period": content.reporting_year if content else None,
            # Citation coordinates remain child/table coordinates, not the full
            # parent range used only as LLM context.
            "page_start": item.page_number,
            "page_end": item.page_end or item.page_number,
            "section": MemoBatchRetriever.clean_label(item.section_title),
            "locator": item.source_reference,
        }

    @classmethod
    def _normalize_generated_text(
        cls,
        result: dict[str, Any],
        *,
        batch: MemoBatch,
    ) -> dict[str, Any]:
        normalized = dict(result)
        summary = normalized.get("summary")
        if isinstance(summary, str):
            normalized["summary"] = cls._limit_words(
                summary,
                batch.output.summary_words,
            )

        caveats = normalized.get("caveats")
        if isinstance(caveats, list):
            normalized["caveats"] = [
                cls._limit_words(str(caveat), 30)
                for caveat in caveats[: batch.output.max_caveats]
                if str(caveat).strip()
            ]

        facts = normalized.get("facts")
        if isinstance(facts, list):
            cleaned_facts = []
            for fact in facts[: batch.output.max_facts]:
                if not isinstance(fact, dict):
                    continue
                cleaned = dict(fact)
                if isinstance(cleaned.get("label"), str):
                    cleaned["label"] = cls._limit_words(cleaned["label"], 10)
                if isinstance(cleaned.get("period"), str):
                    cleaned["period"] = cls._limit_words(cleaned["period"], 10)
                if isinstance(cleaned.get("unit"), str):
                    cleaned["unit"] = cls._limit_words(cleaned["unit"], 5)
                cleaned_facts.append(cleaned)
            normalized["facts"] = cleaned_facts

        observations = normalized.get("observations")
        if isinstance(observations, list):
            cleaned_observations = []
            for observation in observations[: batch.output.max_observations]:
                if not isinstance(observation, dict):
                    continue
                cleaned = dict(observation)
                if isinstance(cleaned.get("key"), str):
                    cleaned["key"] = cls._safe_key(cleaned["key"])
                if isinstance(cleaned.get("title"), str):
                    cleaned["title"] = cls._limit_words(cleaned["title"], 12)
                if isinstance(cleaned.get("text"), str):
                    cleaned["text"] = cls._limit_words(cleaned["text"], 50)
                cleaned_observations.append(cleaned)
            normalized["observations"] = cleaned_observations

        items = normalized.get("items")
        if isinstance(items, list):
            cleaned_items = []
            for item in items[: batch.output.max_items]:
                if not isinstance(item, dict):
                    continue
                cleaned = dict(item)
                if isinstance(cleaned.get("item_id"), str):
                    cleaned["item_id"] = cls._safe_key(cleaned["item_id"])
                if isinstance(cleaned.get("title"), str):
                    cleaned["title"] = cls._limit_words(cleaned["title"], 12)
                if isinstance(cleaned.get("description"), str):
                    cleaned["description"] = cls._limit_words(
                        cleaned["description"],
                        50,
                    )
                item_caveats = cleaned.get("caveats")
                if isinstance(item_caveats, list):
                    cleaned["caveats"] = [
                        cls._limit_words(str(caveat), 30)
                        for caveat in item_caveats[:1]
                        if str(caveat).strip()
                    ]
                cleaned_items.append(cleaned)
            normalized["items"] = cleaned_items

        return normalized

    @staticmethod
    def _limit_words(value: str, maximum_words: int) -> str:
        cleaned = re.sub(r"\s+", " ", value).strip()
        if not cleaned:
            return cleaned
        words = cleaned.split()
        if len(words) <= maximum_words:
            return cleaned
        shortened = " ".join(words[:maximum_words]).rstrip(" ,;:-")
        if shortened and shortened[-1] not in ".!?":
            shortened += "."
        return shortened

    @staticmethod
    def _safe_key(value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip())
        cleaned = re.sub(r"_+", "_", cleaned)
        return cleaned.strip("_")[:50] or "item"
