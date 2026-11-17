from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.ai.retrieval.section_retriever import MemoBatchRetriever, RetrievalRequest
from app.services.credit_memo_batch_definitions import BATCHES


class FakeRetriever:
    def __init__(self, items):
        self.items = items
        self.call = None

    def search(self, **kwargs):
        self.call = kwargs
        return list(self.items)


def evidence(
    content_id: int,
    *,
    child_text: str,
    parent_text: str,
    parent_id: int | None,
    kind: str = "CHILD_CHUNK",
    score: float = 0.9,
):
    return SimpleNamespace(
        content_id=content_id,
        parent_content_id=parent_id,
        text=child_text,
        context_text=parent_text,
        content_type=kind,
        score=score,
        page_number=1,
        page_end=1,
        section_title="Test Section",
        source_reference="Test.pdf, page 1",
        metadata={"document_id": 1},
    )


class MemoRetrievalV2Tests(unittest.TestCase):
    @patch("app.ai.retrieval.section_retriever.get_embedding_client")
    def test_uses_parent_context_but_preserves_child_citation(self, embedder):
        embedder.return_value.embed_text.return_value = [0.1]
        item = evidence(
            11,
            child_text="relevant child",
            parent_text="full parent context",
            parent_id=101,
        )
        fake = FakeRetriever([item])
        batch = next(value for value in BATCHES if value.key == "legal_identity")
        _, packet = MemoBatchRetriever(fake).retrieve(
            request=RetrievalRequest(1, "APP-1", "Borrower"),
            batch=batch,
        )
        self.assertEqual(packet[0]["text"], "full parent context")
        self.assertEqual(packet[0]["retrieved_child_text"], "relevant child")
        self.assertEqual(packet[0]["parent_content_id"], 101)

    @patch("app.ai.retrieval.section_retriever.get_embedding_client")
    def test_batch_final_context_limit_is_two(self, embedder):
        embedder.return_value.embed_text.return_value = [0.1]
        items = [
            evidence(
                index,
                child_text=f"child {index}",
                parent_text=f"parent {index}",
                parent_id=100 + index,
            )
            for index in range(1, 5)
        ]
        fake = FakeRetriever(items)
        batch = next(value for value in BATCHES if value.key == "legal_identity")
        _, packet = MemoBatchRetriever(fake).retrieve(
            request=RetrievalRequest(1, "APP-1", "Borrower"),
            batch=batch,
        )
        self.assertEqual(len(packet), 2)
        self.assertEqual(fake.call["top_k"], 2)
        self.assertEqual(fake.call["candidate_k"], batch.candidate_k)

    @patch("app.ai.retrieval.section_retriever.get_embedding_client")
    def test_oversized_parent_is_skipped_not_cut(self, embedder):
        embedder.return_value.embed_text.return_value = [0.1]
        batch = next(value for value in BATCHES if value.key == "legal_identity")
        oversized = evidence(
            1,
            child_text="child one",
            parent_text="x" * (batch.max_evidence_characters + 1),
            parent_id=101,
        )
        valid = evidence(
            2,
            child_text="child two",
            parent_text="valid context",
            parent_id=102,
        )
        _, packet = MemoBatchRetriever(FakeRetriever([oversized, valid])).retrieve(
            request=RetrievalRequest(1, "APP-1", "Borrower"),
            batch=batch,
        )
        self.assertEqual([row["text"] for row in packet], ["valid context"])

    @patch("app.ai.retrieval.section_retriever.get_embedding_client")
    def test_table_uses_table_text_as_context(self, embedder):
        embedder.return_value.embed_text.return_value = [0.1]
        table = evidence(
            5,
            child_text="| Revenue | 100 |",
            parent_text="ignored",
            parent_id=None,
            kind="TABLE_DATA",
        )
        batch = next(value for value in BATCHES if value.key == "revenue_profit")
        _, packet = MemoBatchRetriever(FakeRetriever([table])).retrieve(
            request=RetrievalRequest(1, "APP-1", "Borrower"),
            batch=batch,
        )
        self.assertEqual(packet[0]["text"], "| Revenue | 100 |")


if __name__ == "__main__":
    unittest.main()
