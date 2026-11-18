from __future__ import annotations

import unittest
from unittest.mock import patch

from app.ai.retrieval.faiss_retriever import RetrievedEvidence
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
    text: str,
    kind: str = "PARENT_SECTION",
    parent_id: int | None = None,
    chunk_id: str | None = None,
    related_parents: list[dict] | None = None,
):
    return RetrievedEvidence(
        source_id=f"DOC1-CONTENT-{content_id}",
        score=0.9,
        raw_score=0.9,
        vector_id=content_id,
        content_id=content_id,
        parent_content_id=parent_id if parent_id is not None else content_id,
        content_type=kind,
        text=text,
        section_title="Test Section",
        page_number=1,
        page_end=1,
        source_reference="Test.pdf, page 1",
        table_image_path=None,
        visual_image_path=None,
        metadata={"document_id": 1},
        chunk_id=chunk_id or f"PG-{content_id}",
        related_parents=related_parents or [],
    )


class MemoRetrievalV3Tests(unittest.TestCase):
    @patch("app.ai.retrieval.section_retriever.get_embedding_client")
    def test_packet_contains_parent_and_table_only(self, embedder):
        embedder.return_value.embed_text.return_value = [0.1]
        batch = next(value for value in BATCHES if value.key == "revenue_profit")
        raw = [
            evidence(101, text="full parent context"),
            evidence(
                201,
                text="| Revenue | 100 |",
                kind="TABLE_DATA",
                parent_id=101,
            ),
        ]
        _, packet = MemoBatchRetriever(FakeRetriever(raw)).retrieve(
            request=RetrievalRequest(1, "APP-1", "Borrower"),
            batch=batch,
        )
        self.assertEqual(
            [item["source_type"] for item in packet],
            ["PARENT", "TABLE"],
        )
        self.assertFalse(any("retrieved_child" in item for item in packet))

    @patch("app.ai.retrieval.section_retriever.get_embedding_client")
    def test_parent_text_is_sent_verbatim(self, embedder):
        embedder.return_value.embed_text.return_value = [0.1]
        batch = next(value for value in BATCHES if value.key == "legal_identity")
        text = "parent context " * 2000
        _, packet = MemoBatchRetriever(
            FakeRetriever([evidence(101, text=text)])
        ).retrieve(
            request=RetrievalRequest(1, "APP-1", "Borrower"),
            batch=batch,
        )
        self.assertEqual(packet[0]["text"], text.strip())
        self.assertEqual(packet[0]["source_id"], "DOC1-CONTENT-101")

    @patch("app.ai.retrieval.section_retriever.get_embedding_client")
    def test_table_text_is_sent_verbatim(self, embedder):
        embedder.return_value.embed_text.return_value = [0.1]
        batch = next(value for value in BATCHES if value.key == "revenue_profit")
        table_text = "| Revenue | 100 |\n" * 3000
        _, packet = MemoBatchRetriever(
            FakeRetriever(
                [
                    evidence(
                        201,
                        text=table_text,
                        kind="TABLE_DATA",
                        parent_id=101,
                    )
                ]
            )
        ).retrieve(
            request=RetrievalRequest(1, "APP-1", "Borrower"),
            batch=batch,
        )
        self.assertEqual(packet[0]["text"], table_text.strip())
        self.assertEqual(packet[0]["source_type"], "TABLE")

    @patch("app.ai.retrieval.section_retriever.get_embedding_client")
    def test_search_uses_fixed_candidate_and_parent_limits(self, embedder):
        embedder.return_value.embed_text.return_value = [0.1]
        batch = next(value for value in BATCHES if value.key == "legal_identity")
        fake = FakeRetriever([evidence(101, text="parent")])
        MemoBatchRetriever(fake).retrieve(
            request=RetrievalRequest(1, "APP-1", "Borrower"),
            batch=batch,
        )
        self.assertEqual(fake.call["top_k"], 2)
        self.assertEqual(fake.call["candidate_k"], 24)

    @patch("app.ai.retrieval.section_retriever.get_embedding_client")
    def test_related_parents_pass_through(self, embedder):
        embedder.return_value.embed_text.return_value = [0.1]
        batch = next(value for value in BATCHES if value.key == "legal_identity")
        related = [
            {
                "parent_id": "PG-SEC-0002",
                "content_id": 102,
                "document_id": 1,
                "section_title": "Continuation",
                "pages": "2",
            }
        ]
        _, packet = MemoBatchRetriever(
            FakeRetriever(
                [evidence(101, text="parent", related_parents=related)]
            )
        ).retrieve(
            request=RetrievalRequest(1, "APP-1", "Borrower"),
            batch=batch,
        )
        self.assertEqual(packet[0]["related_parents"], related)


if __name__ == "__main__":
    unittest.main()
