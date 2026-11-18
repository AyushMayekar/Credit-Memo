from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("EMBEDDING_API_KEY", "test")
os.environ.setdefault("LLM_API_KEY", "test")
os.environ.setdefault("LLM_BASE_URL", "http://localhost")

from types import SimpleNamespace

from app.ai.retrieval.faiss_retriever import RetrievedEvidence
from app.ai.retrieval.json_utils import LlmJsonError
from app.ai.retrieval.section_retriever import RetrievalRequest
from app.services.credit_memo_batch_definitions import BATCHES
from app.services.credit_memo_extraction_service import CreditMemoExtractionService


def parent_entry(
    content_id: int = 101,
    *,
    related: list[dict] | None = None,
) -> dict:
    return {
        "source_id": f"DOC1-CONTENT-{content_id}",
        "source_type": "PARENT",
        "content_type": "PARENT_SECTION",
        "content_id": content_id,
        "parent_content_id": content_id,
        "chunk_id": f"PG-{content_id}",
        "document_id": 1,
        "page": 1,
        "page_end": 1,
        "section": "Financials",
        "document_name": "Test.pdf",
        "text": "Revenue was 100.",
        "related_parents": related or [],
    }


def packet() -> list[dict]:
    return [
        parent_entry(
            related=[
                {
                    "parent_id": "PG-2",
                    "content_id": 102,
                    "document_id": 1,
                    "section_title": "Continuation",
                    "pages": "2",
                }
            ]
        )
    ]


def narrative_answer(source_id: str = "S1") -> dict:
    return {
        "status": "available",
        "summary": "The borrower has operations.",
        "caveats": [],
        "source_ids": [source_id],
        "observations": [
            {
                "key": "operations",
                "title": "Operations",
                "text": "The borrower operates.",
                "source_ids": [source_id],
            }
        ],
    }


def facts_answer(source_id: str = "S1") -> dict:
    return {
        "status": "available",
        "summary": "Revenue was 100.",
        "caveats": [],
        "source_ids": [source_id],
        "facts": [
            {
                "label": "Revenue",
                "period": "FY2024",
                "value": 100,
                "unit": "USD",
                "source_ids": [source_id],
            }
        ],
    }


def batch(key: str):
    return next(value for value in BATCHES if value.key == key)


class MemoRetryLoopTests(unittest.TestCase):
    def setUp(self):
        self.service = CreditMemoExtractionService()
        self.request = RetrievalRequest(1, "APP-1", "Borrower")
        self.facts = {
            "borrower_name": "Borrower",
            "facility_amount": 1000,
            "currency": "USD",
            "tenure_months": 12,
        }

    def run_agent(self, *, key: str, responses: list, extra_patches=()):
        with patch.object(
            self.service,
            "_invoke_json_once",
            side_effect=responses,
        ):
            context = []
            for item in extra_patches:
                context.append(item)
            for item in context:
                item.start()
            try:
                return self.service._run_agent(
                    session=None,
                    request=self.request,
                    batch=batch(key),
                    application_facts=self.facts,
                    retriever=object(),
                    base_retriever=object(),
                    packet=packet(),
                    sources={},
                )
            finally:
                for item in context:
                    item.stop()

    def test_answer_on_initial_call_is_not_a_retry(self):
        result, _, attempts, retries, last_action, _, _ = self.run_agent(
            key="revenue_profit",
            responses=[({"action": "ANSWER", "answer": facts_answer()}, 100)],
        )
        self.assertEqual(attempts, 1)
        self.assertEqual(retries, 0)
        self.assertEqual(last_action, "ANSWER")
        self.assertEqual(result["source_ids"], ["DOC1-CONTENT-101"])

    def test_less_important_batch_gets_one_retry_then_answer_only(self):
        search = patch.object(
            self.service,
            "_vector_search",
            return_value=(packet(), {}, None),
        )
        result, _, attempts, retries, last_action, _, _ = self.run_agent(
            key="ownership_background",
            responses=[
                (
                    {
                        "action": "VECTOR_SEARCH",
                        "reason": "Need a different query",
                        "search_query": "ownership history",
                    },
                    100,
                ),
                (narrative_answer(), 100),
            ],
            extra_patches=[search],
        )
        self.assertEqual(attempts, 2)
        self.assertEqual(retries, 1)
        self.assertEqual(last_action, "ANSWER_ONLY")
        self.assertEqual(result["source_ids"], ["DOC1-CONTENT-101"])

    def test_important_batch_allows_three_retries_then_answer_only(self):
        search = patch.object(
            self.service,
            "_vector_search",
            return_value=(packet(), {}, None),
        )
        result, _, attempts, retries, last_action, _, _ = self.run_agent(
            key="revenue_profit",
            responses=[
                (
                    {
                        "action": "VECTOR_SEARCH",
                        "reason": "First search",
                        "search_query": "revenue",
                    },
                    100,
                ),
                (
                    {
                        "action": "VECTOR_SEARCH",
                        "reason": "Second search",
                        "search_query": "profit",
                    },
                    100,
                ),
                (
                    {
                        "action": "VECTOR_SEARCH",
                        "reason": "Third search",
                        "search_query": "income",
                    },
                    100,
                ),
                (facts_answer(), 100),
            ],
            extra_patches=[search],
        )
        self.assertEqual(attempts, 4)
        self.assertEqual(retries, 3)
        self.assertEqual(last_action, "ANSWER_ONLY")
        self.assertEqual(result["source_ids"], ["DOC1-CONTENT-101"])

    def test_last_retry_cannot_call_a_tool(self):
        search = patch.object(
            self.service,
            "_vector_search",
            return_value=(packet(), {}, None),
        )
        result, _, attempts, retries, last_action, _, _ = self.run_agent(
            key="ownership_background",
            responses=[
                (
                    {
                        "action": "VECTOR_SEARCH",
                        "reason": "First search",
                        "search_query": "ownership",
                    },
                    100,
                ),
                (
                    {
                        "action": "VECTOR_SEARCH",
                        "reason": "Illegal final action",
                        "search_query": "control",
                    },
                    100,
                ),
            ],
            extra_patches=[search],
        )
        self.assertEqual(attempts, 2)
        self.assertEqual(retries, 1)
        self.assertEqual(last_action, "ANSWER_ONLY")
        self.assertEqual(result["status"], "pending_review")

    def test_invalid_json_consumes_one_retry(self):
        result, _, attempts, retries, _, _, _ = self.run_agent(
            key="ownership_background",
            responses=[
                LlmJsonError("not json"),
                (narrative_answer(), 100),
            ],
        )
        self.assertEqual(attempts, 2)
        self.assertEqual(retries, 1)
        self.assertEqual(result["source_ids"], ["DOC1-CONTENT-101"])

    def test_unknown_source_id_is_rejected(self):
        result, _, attempts, retries, _, _, _ = self.run_agent(
            key="ownership_background",
            responses=[
                (
                    {"action": "ANSWER", "answer": narrative_answer("S9")},
                    100,
                ),
                (narrative_answer(), 100),
            ],
        )
        self.assertEqual(attempts, 2)
        self.assertEqual(retries, 1)
        self.assertEqual(result["source_ids"], ["DOC1-CONTENT-101"])

    def test_fetch_rejects_unknown_parent_id(self):
        with self.assertRaises(ValueError):
            self.service._validate_action(
                {
                    "action": "FETCH_RELATED_PARENTS",
                    "reason": "Need more",
                    "parent_ids": ["PG-999"],
                },
                packet(),
            )

    def test_fetch_is_rejected_when_two_parents_are_present(self):
        two = packet() + [parent_entry(102)]
        with self.assertRaises(ValueError):
            self.service._validate_action(
                {
                    "action": "FETCH_RELATED_PARENTS",
                    "reason": "Need more",
                    "parent_ids": ["PG-2"],
                },
                two,
            )

    def test_vector_search_requires_a_query(self):
        with self.assertRaises(ValueError):
            self.service._validate_action(
                {
                    "action": "VECTOR_SEARCH",
                    "reason": "Need more",
                    "search_query": "",
                },
                packet(),
            )

    def test_fetch_adds_one_related_parent(self):
        class FakeSession:
            def get(self, model, identifier):
                if model.__name__ == "DocumentContent":
                    return SimpleNamespace(
                        document_id=1,
                        reporting_year="FY2024",
                    )
                return SimpleNamespace(
                    original_filename="Test.pdf",
                    document_type="annual_report",
                )

        class FakeBaseRetriever:
            def fetch_parents_by_chunk_ids(self, **kwargs):
                return [SimpleNamespace(id=102)]

            def parent_evidence(self, parent, **kwargs):
                return RetrievedEvidence(
                    source_id="DOC1-CONTENT-102",
                    score=0.5,
                    raw_score=0.5,
                    vector_id=2,
                    content_id=102,
                    parent_content_id=102,
                    content_type="PARENT_SECTION",
                    text="related parent text",
                    section_title="Continuation",
                    page_number=2,
                    page_end=2,
                    source_reference="Test.pdf, page 2",
                    table_image_path=None,
                    visual_image_path=None,
                    metadata={"document_id": 1},
                    chunk_id="PG-2",
                    related_parents=[],
                )

        new_packet, new_sources, error = self.service._fetch_related_parents(
            session=FakeSession(),
            request=self.request,
            base_retriever=FakeBaseRetriever(),
            packet=packet(),
            sources={},
            action={
                "action": "FETCH_RELATED_PARENTS",
                "reason": "Need the continuation",
                "parent_ids": ["PG-2"],
            },
        )
        self.assertIsNone(error)
        self.assertEqual(len(new_packet), 2)
        self.assertEqual(new_packet[-1]["source_type"], "PARENT")
        self.assertIn("DOC1-CONTENT-102", new_sources)


if __name__ == "__main__":
    unittest.main()
