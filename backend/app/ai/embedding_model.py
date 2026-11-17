from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Sequence

from openai import OpenAI

from app.core.config import settings


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    batch_index: int
    item_start: int
    item_end: int
    estimated_tokens: int
    texts: list[str]


@dataclass(frozen=True, slots=True)
class EmbeddingBatchMetrics:
    request_count: int
    item_count: int
    estimated_tokens: int
    elapsed_seconds: float
    batch_elapsed_seconds: list[float]


class EmbeddingClient:
    """Token-safe embedding client with deterministic batching and retry support."""

    def __init__(self) -> None:
        self.client = OpenAI(
            api_key="dummy",
            base_url=settings.llm_base_url,
            default_headers={
                "x-litellm-api-key": settings.embedding_api_key,
            },
            timeout=60.0,
            max_retries=3,
        )

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self.client.embeddings.create(
            model=settings.embedding_model,
            input=texts,
        )
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors = [item.embedding for item in ordered]
        if len(vectors) != len(texts):
            raise RuntimeError(
                "Embedding API returned an unexpected vector count. "
                f"Expected {len(texts)}, received {len(vectors)}."
            )
        return vectors

    def build_batches(
        self,
        texts: Sequence[str],
        batch_size: int | None = None,
        batch_token_limit: int | None = None,
    ) -> list[EmbeddingBatch]:
        maximum_items = max(1, batch_size or settings.embedding_batch_size)
        maximum_tokens = max(
            1,
            batch_token_limit or settings.embedding_batch_token_limit,
        )
        batches: list[EmbeddingBatch] = []
        current: list[str] = []
        current_tokens = 0
        current_start = 0

        for index, raw_text in enumerate(texts):
            if not isinstance(raw_text, str):
                raise TypeError(f"Embedding input at index {index} must be a string.")
            text = raw_text.strip()
            if not text:
                raise ValueError(f"Embedding input at index {index} is empty.")
            tokens = self._estimate_tokens(text)
            if tokens > maximum_tokens:
                raise ValueError(
                    f"Embedding input {index} is approximately {tokens} tokens, "
                    f"above the configured per-request limit of {maximum_tokens}."
                )

            exceeds_items = len(current) >= maximum_items
            exceeds_tokens = bool(current) and current_tokens + tokens > maximum_tokens
            if exceeds_items or exceeds_tokens:
                batches.append(
                    EmbeddingBatch(
                        batch_index=len(batches) + 1,
                        item_start=current_start,
                        item_end=index - 1,
                        estimated_tokens=current_tokens,
                        texts=current,
                    )
                )
                current = []
                current_tokens = 0
                current_start = index

            current.append(text)
            current_tokens += tokens

        if current:
            batches.append(
                EmbeddingBatch(
                    batch_index=len(batches) + 1,
                    item_start=current_start,
                    item_end=len(texts) - 1,
                    estimated_tokens=current_tokens,
                    texts=current,
                )
            )
        return batches

    def embed_texts_batched(
        self,
        texts: list[str],
        batch_size: int | None = None,
        batch_token_limit: int | None = None,
        *,
        return_metrics: bool = False,
    ) -> list[list[float]] | tuple[list[list[float]], EmbeddingBatchMetrics]:
        batches = self.build_batches(texts, batch_size, batch_token_limit)
        vectors: list[list[float]] = []
        batch_times: list[float] = []
        started = time.perf_counter()

        for batch in batches:
            batch_started = time.perf_counter()
            print(
                "[EMBEDDING] "
                f"Batch {batch.batch_index}/{len(batches)}: "
                f"{len(batch.texts)} item(s), "
                f"approximately {batch.estimated_tokens} tokens"
            )
            vectors.extend(self.embed_texts(batch.texts))
            batch_times.append(round(time.perf_counter() - batch_started, 4))

        if len(vectors) != len(texts):
            raise RuntimeError(
                f"Expected {len(texts)} vectors, received {len(vectors)}."
            )

        metrics = EmbeddingBatchMetrics(
            request_count=len(batches),
            item_count=len(texts),
            estimated_tokens=sum(batch.estimated_tokens for batch in batches),
            elapsed_seconds=round(time.perf_counter() - started, 4),
            batch_elapsed_seconds=batch_times,
        )
        return (vectors, metrics) if return_metrics else vectors

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        lexical_units = len(re.findall(r"\w+|[^\w\s]", text))
        character_estimate = max(1, len(text) // 3)
        return max(1, lexical_units, character_estimate)


def get_embedding_client() -> EmbeddingClient:
    return EmbeddingClient()
