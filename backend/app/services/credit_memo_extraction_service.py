from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from jsonschema import Draft202012Validator

from app.ai.llm import get_llm
from app.ai.prompts.credit_memo_prompts import (
    build_batch_messages,
    build_recommendation_messages,
    recommendation_contract,
)
from app.ai.retrieval.faiss_retriever import ApplicationFaissRetriever
from app.ai.retrieval.json_utils import LlmJsonError, parse_json_object
from app.ai.retrieval.section_retriever import MemoBatchRetriever, RetrievalRequest
from app.core.config import settings
from app.db.session import SessionLocal
from app.services.credit_memo_batch_definitions import BATCHES, MemoBatch


class CreditMemoExtractionService:
    MAX_CONCURRENCY = 3
    MAX_PARENTS = 2

    ACTION_SCHEMAS = {
        "ANSWER": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action", "answer"],
            "properties": {
                "action": {"const": "ANSWER"},
                "answer": {"type": "object"},
            },
        },
        "FETCH_RELATED_PARENTS": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action", "reason", "parent_ids"],
            "properties": {
                "action": {"const": "FETCH_RELATED_PARENTS"},
                "reason": {"type": "string", "minLength": 1, "maxLength": 500},
                "parent_ids": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 2,
                    "items": {"type": "string", "minLength": 1},
                },
            },
        },
        "VECTOR_SEARCH": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action", "reason", "search_query"],
            "properties": {
                "action": {"const": "VECTOR_SEARCH"},
                "reason": {"type": "string", "minLength": 1, "maxLength": 500},
                "search_query": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 1000,
                },
            },
        },
    }

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
            base_retriever = ApplicationFaissRetriever(session, index_path)
            retriever = MemoBatchRetriever(base_retriever)
            raw, packet = retriever.retrieve(request=request, batch=batch)
            sources = self._sources_for(session, raw)

            if not packet:
                return self._fallback_result(
                    batch,
                    sources,
                    attempts=0,
                    status="not_disclosed",
                    reason="No relevant evidence was retrieved.",
                    last_action="NONE",
                )

            (
                result,
                sources,
                attempts,
                retries,
                last_action,
                characters,
                final_packet,
            ) = self._run_agent(
                session=session,
                request=request,
                batch=batch,
                application_facts=application_facts,
                retriever=retriever,
                base_retriever=base_retriever,
                packet=packet,
                sources=sources,
            )

        return (
            result,
            sources,
            {
                "batch": batch.key,
                "section": batch.section_key,
                "kind": batch.output.kind,
                "evidence": len(final_packet),
                "attempts": attempts,
                "retries": retries,
                "max_retries": batch.max_retries,
                "last_action": last_action,
                "output_characters": characters,
                "retrieval_context": "parent_table_v3",
                "parent_context_ids": [
                    item.get("parent_content_id")
                    for item in final_packet
                    if item.get("source_type") == "PARENT"
                ],
            },
        )

    def _run_agent(
        self,
        *,
        session,
        request: RetrievalRequest,
        batch: MemoBatch,
        application_facts: dict[str, Any],
        retriever: MemoBatchRetriever,
        base_retriever: ApplicationFaissRetriever,
        packet: list[dict[str, Any]],
        sources: dict[str, dict[str, Any]],
    ) -> tuple[
        dict[str, Any],
        dict[str, dict[str, Any]],
        int,
        int,
        str,
        int,
        list[dict[str, Any]],
    ]:
        """Run the bounded action/answer loop for one memo batch.

        The initial retrieval and first LLM call are not retries. Every
        subsequent LLM call counts against the batch retry budget. The last
        retry is answer-only and cannot call a tool.
        """
        max_retries = max(1, int(batch.max_retries))
        retries_used = 0
        attempts = 0
        answer_only = False
        last_error: str | None = None
        last_action = "INITIAL"
        current_packet = list(packet)
        current_sources = dict(sources)

        while True:
            attempts += 1
            messages, contract, aliases = build_batch_messages(
                batch=batch,
                application_facts=application_facts,
                evidence=current_packet,
                answer_only=answer_only,
                retry_state={
                    "attempt": retries_used,
                    "max_retries": max_retries,
                },
                last_error=last_error,
            )

            try:
                payload, characters = self._invoke_json_once(
                    messages,
                    max_tokens=batch.max_output_tokens,
                    label=f"Memo batch '{batch.key}'",
                )
            except (LlmJsonError, ValueError) as exc:
                if answer_only:
                    result, fallback_sources, _ = self._agent_fallback(
                        batch,
                        current_sources,
                        attempts=attempts,
                        reason=f"The final attempt was invalid: {exc}",
                        last_action="ANSWER_ONLY",
                        packet=current_packet,
                    )
                    return (
                        result,
                        fallback_sources,
                        attempts,
                        max(0, attempts - 1),
                        "ANSWER_ONLY",
                        0,
                        current_packet,
                    )
                retries_used += 1
                last_error = str(exc)
                if retries_used >= max_retries:
                    answer_only = True
                continue

            if answer_only:
                try:
                    result = self._validate_and_finalize(
                        payload,
                        contract=contract,
                        aliases=aliases,
                        batch=batch,
                    )
                except ValueError as exc:
                    result, fallback_sources, _ = self._agent_fallback(
                        batch,
                        current_sources,
                        attempts=attempts,
                        reason=f"The final attempt was invalid: {exc}",
                        last_action="ANSWER_ONLY",
                        packet=current_packet,
                    )
                    return (
                        result,
                        fallback_sources,
                        attempts,
                        max(0, attempts - 1),
                        "ANSWER_ONLY",
                        0,
                        current_packet,
                    )
                return (
                    result,
                    current_sources,
                    attempts,
                    retries_used,
                    "ANSWER_ONLY",
                    characters,
                    current_packet,
                )

            action = payload.get("action") if isinstance(payload, dict) else None
            if action == "ANSWER":
                try:
                    self._validate_action(payload, current_packet)
                    result = self._validate_and_finalize(
                        payload.get("answer"),
                        contract=contract,
                        aliases=aliases,
                        batch=batch,
                    )
                except ValueError as exc:
                    retries_used += 1
                    last_error = str(exc)
                    if retries_used >= max_retries:
                        answer_only = True
                    continue
                return (
                    result,
                    current_sources,
                    attempts,
                    retries_used,
                    "ANSWER",
                    characters,
                    current_packet,
                )

            if action in {"FETCH_RELATED_PARENTS", "VECTOR_SEARCH"}:
                try:
                    action = self._validate_action(payload, current_packet)
                except ValueError as exc:
                    retries_used += 1
                    last_error = str(exc)
                    if retries_used >= max_retries:
                        answer_only = True
                    continue

                if action["action"] == "FETCH_RELATED_PARENTS":
                    current_packet, new_sources, tool_error = (
                        self._fetch_related_parents(
                            session=session,
                            request=request,
                            base_retriever=base_retriever,
                            packet=current_packet,
                            sources=current_sources,
                            action=action,
                        )
                    )
                else:
                    current_packet, new_sources, tool_error = self._vector_search(
                        session=session,
                        request=request,
                        retriever=retriever,
                        batch=batch,
                        action=action,
                    )

                if tool_error is None:
                    current_sources = new_sources
                retries_used += 1
                last_action = action["action"]
                last_error = tool_error
                if retries_used >= max_retries:
                    answer_only = True
                continue

            retries_used += 1
            last_error = (
                "Return exactly one action: ANSWER, FETCH_RELATED_PARENTS, "
                "or VECTOR_SEARCH."
            )
            if retries_used >= max_retries:
                answer_only = True

    def _fetch_related_parents(
        self,
        *,
        session,
        request: RetrievalRequest,
        base_retriever: ApplicationFaissRetriever,
        packet: list[dict[str, Any]],
        sources: dict[str, dict[str, Any]],
        action: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], str | None]:
        allowed = self._allowed_related_parents(packet)
        requested = list(dict.fromkeys(str(x) for x in action["parent_ids"]))
        by_document: dict[int, list[str]] = {}
        for parent_id in requested:
            document_id = allowed.get(parent_id)
            if document_id is None:
                continue
            by_document.setdefault(int(document_id), []).append(parent_id)

        fetched = []
        for document_id, parent_ids in by_document.items():
            fetched.extend(
                base_retriever.fetch_parents_by_chunk_ids(
                    application_id=request.application_id,
                    document_id=document_id,
                    chunk_ids=parent_ids,
                )
            )

        if not fetched:
            return (
                packet,
                sources,
                "No related parents were found for the requested IDs.",
            )

        existing_parent_ids = {
            item.get("content_id")
            for item in packet
            if item.get("source_type") == "PARENT"
        }
        capacity = self.MAX_PARENTS - len(existing_parent_ids)
        if capacity <= 0:
            return (
                packet,
                sources,
                "The parent limit of 2 is already reached.",
            )

        new_packet = list(packet)
        new_sources = dict(sources)
        added = 0
        for parent in fetched:
            if added >= capacity:
                break
            if parent.id in existing_parent_ids:
                continue
            evidence = base_retriever.parent_evidence(
                parent,
                application_id=request.application_id,
            )
            entry = MemoBatchRetriever.packet_entry(evidence)
            new_packet.append(entry)
            new_sources[evidence.source_id] = self._source(
                session,
                evidence,
                evidence.source_id,
            )
            existing_parent_ids.add(parent.id)
            added += 1

        if added == 0:
            return (
                packet,
                sources,
                "The requested parents were already present.",
            )
        return new_packet, new_sources, None

    def _vector_search(
        self,
        *,
        session,
        request: RetrievalRequest,
        retriever: MemoBatchRetriever,
        batch: MemoBatch,
        action: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], str | None]:
        raw, packet = retriever.search(
            request=request,
            query=action["search_query"],
            batch=batch,
        )
        if not packet:
            return (
                [],
                {},
                "The vector search returned no evidence.",
            )
        return packet, self._sources_for(session, raw), None

    def _validate_action(
        self,
        payload: dict[str, Any],
        packet: list[dict[str, Any]],
    ) -> dict[str, Any]:
        action_name = payload.get("action") if isinstance(payload, dict) else None
        schema = self.ACTION_SCHEMAS.get(action_name)
        if schema is None:
            raise ValueError(
                "Return exactly one action: ANSWER, FETCH_RELATED_PARENTS, "
                "or VECTOR_SEARCH."
            )
        errors = [
            (
                f"{'/'.join(str(value) for value in error.absolute_path) or '$'}: "
                f"{error.message}"
            )
            for error in Draft202012Validator(schema).iter_errors(payload)
        ]
        if errors:
            raise ValueError("; ".join(errors[:5]))

        if action_name == "FETCH_RELATED_PARENTS":
            current_parents = len(
                {
                    item.get("content_id")
                    for item in packet
                    if item.get("source_type") == "PARENT"
                }
            )
            if current_parents >= self.MAX_PARENTS:
                raise ValueError(
                    "The parent limit of 2 is already reached; answer or use "
                    "VECTOR_SEARCH."
                )
            allowed = self._allowed_related_parents(packet)
            unknown = [
                parent_id
                for parent_id in payload["parent_ids"]
                if parent_id not in allowed
            ]
            if unknown:
                raise ValueError(
                    "Unknown related parent IDs: " + ", ".join(unknown[:4])
                )
        return payload

    def _validate_and_finalize(
        self,
        result: Any,
        *,
        contract: dict[str, Any],
        aliases: dict[str, str],
        batch: MemoBatch,
    ) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise ValueError("The answer must be one JSON object.")
        result = self._normalize_generated_text(result, batch=batch)
        errors = [
            (
                f"{'/'.join(str(value) for value in error.absolute_path) or '$'}: "
                f"{error.message}"
            )
            for error in Draft202012Validator(contract).iter_errors(result)
        ]
        if errors:
            raise ValueError("; ".join(errors[:5]))

        unknown = [
            source_id
            for source_id in self._collect_source_ids(result)
            if source_id not in aliases
        ]
        if unknown:
            raise ValueError(
                "Unknown source IDs: " + ", ".join(sorted(set(unknown))[:4])
            )

        result = self._expand_aliases(result, aliases)
        return self._normalize(result)

    def _agent_fallback(
        self,
        batch: MemoBatch,
        sources: dict[str, dict[str, Any]],
        *,
        attempts: int,
        reason: str,
        last_action: str,
        packet: list[dict[str, Any]],
    ):
        return self._fallback_result(
            batch,
            sources,
            attempts=attempts,
            status="pending_review",
            reason=reason,
            last_action=last_action,
            packet=packet,
        )

    def _fallback_result(
        self,
        batch: MemoBatch,
        sources: dict[str, dict[str, Any]],
        *,
        attempts: int,
        status: str,
        reason: str,
        last_action: str,
        packet: list[dict[str, Any]] | None = None,
    ):
        packet = packet or []
        return (
            self._normalize(
                {
                    "status": status,
                    "summary": None,
                    "caveats": [reason],
                    "source_ids": [],
                }
            ),
            sources,
            {
                "batch": batch.key,
                "section": batch.section_key,
                "kind": batch.output.kind,
                "evidence": len(packet),
                "attempts": attempts,
                "retries": max(0, attempts - 1),
                "max_retries": batch.max_retries,
                "last_action": last_action,
                "output_characters": 0,
                "retrieval_context": "parent_table_v3",
                "parent_context_ids": [
                    item.get("parent_content_id")
                    for item in packet
                    if item.get("source_type") == "PARENT"
                ],
            },
        )

    def recommend(self, *, digest, allowed_source_ids):
        try:
            result, _, _ = self._invoke_json_messages(
                build_recommendation_messages(digest=digest),
                max_tokens=1400,
                label="Recommendation",
            )
        except (LlmJsonError, ValueError):
            return self._recommendation_fallback(
                "The recommendation did not produce a valid structured answer.",
            )
        errors = [
            (
                f"{'/'.join(str(value) for value in error.absolute_path) or '$'}: "
                f"{error.message}"
            )
            for error in Draft202012Validator(
                recommendation_contract()
            ).iter_errors(result)
        ]
        if errors:
            return self._recommendation_fallback(
                "The recommendation did not produce a valid structured answer.",
            )
        return self._filter_sources(result, allowed_source_ids)

    @staticmethod
    def _recommendation_fallback(reason: str) -> dict[str, Any]:
        return {
            "recommendation_status": "PENDING_ANALYST_REVIEW",
            "recommended_amount": None,
            "rationale": None,
            "source_ids": [],
            "conditions": [],
            "required_approvals": [],
            "unresolved_issues": [],
            "caveats": [reason],
        }

    @staticmethod
    def _invoke_json_once(
        messages: list[dict],
        *,
        max_tokens: int,
        label: str,
    ) -> tuple[dict[str, Any], int]:
        llm = get_llm()
        response = llm.chat_response(
            messages,
            temperature=0,
            max_tokens=max_tokens,
        )
        if response.finish_reason in {"length", "max_tokens"}:
            raise ValueError(f"{label} exceeded its {max_tokens}-token output limit.")
        return parse_json_object(response.content), len(response.content)

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
    def _sources_for(session, raw) -> dict[str, dict[str, Any]]:
        return {
            item.source_id: CreditMemoExtractionService._source(
                session,
                item,
                item.source_id,
            )
            for item in raw
        }

    @staticmethod
    def _allowed_related_parents(
        packet: list[dict[str, Any]],
    ) -> dict[str, int]:
        allowed: dict[str, int] = {}
        for item in packet:
            if item.get("source_type") != "PARENT":
                continue
            for related in item.get("related_parents", []):
                parent_id = related.get("parent_id")
                document_id = related.get("document_id")
                if parent_id and document_id is not None:
                    allowed[str(parent_id)] = int(document_id)
        return allowed

    @staticmethod
    def _collect_source_ids(value: Any) -> list[str]:
        output: list[str] = []
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "source_ids" and isinstance(item, list):
                    output.extend(str(source_id) for source_id in item)
                else:
                    output.extend(
                        CreditMemoExtractionService._collect_source_ids(item)
                    )
        elif isinstance(value, list):
            for item in value:
                output.extend(
                    CreditMemoExtractionService._collect_source_ids(item)
                )
        return output

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
            # Citation coordinates remain the parent/table coordinates, not a
            # reconstructed child range.
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
