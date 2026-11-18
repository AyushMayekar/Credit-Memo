from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("EMBEDDING_API_KEY", "test")
os.environ.setdefault("LLM_API_KEY", "test")
os.environ.setdefault("LLM_BASE_URL", "http://localhost")

from app.ai.retrieval.faiss_retriever import RetrievedEvidence
from app.ai.retrieval.json_utils import LlmJsonError
from app.ai.retrieval.workflow import RagWorkflow


class FakeLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    def invoke(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return self.outputs.pop(0)


class FakeSession:
    def scalar(self, query):
        return SimpleNamespace(
            id=7,
            borrower=SimpleNamespace(legal_name="Acme"),
        )


class FakeRetriever:
    def __init__(self, evidence):
        self.evidence = evidence
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return list(self.evidence)


def parent_evidence() -> RetrievedEvidence:
    return RetrievedEvidence(
        source_id="DOC1-CONTENT-101",
        score=0.9,
        raw_score=0.9,
        vector_id=1,
        content_id=101,
        parent_content_id=101,
        content_type="PARENT_SECTION",
        text="Revenue was 100.",
        section_title="Financials",
        page_number=1,
        page_end=1,
        source_reference="Test.pdf, page 1",
        table_image_path=None,
        visual_image_path=None,
        metadata={"document_id": 1},
        chunk_id="PG-1",
        related_parents=[],
    )


def rag_answer(source_id: str = "DOC1-CONTENT-101", *, limitations=None) -> str:
    import json

    return json.dumps(
        {
            "response_type": "rag_answer",
            "answer": "Revenue was 100.",
            "key_points": ["Revenue was 100."],
            "sources": [{"source_id": source_id, "claim": "Revenue"}],
            "limitations": limitations or [],
        }
    )


class RagWorkflowContractTests(unittest.TestCase):
    def test_app_help_uses_no_application_or_retriever_calls(self):
        workflow = RagWorkflow(session=None, retriever=None)
        workflow.llm = FakeLLM(
            [
                '{"route":"APP_HELP","reason":"app question"}',
                '{"response_type":"general","answer":"This app creates credit memos.","sources":[],"limitations":[]}',
            ]
        )
        state = workflow.invoke(
            application_reference="APP-1",
            request_type="USER_QUERY",
            query="What does this app do?",
        )
        self.assertEqual(state["route"], "APP_HELP")
        self.assertEqual(state["response"]["response_type"], "general")

    def test_out_of_scope_returns_fixed_refusal(self):
        workflow = RagWorkflow(session=None, retriever=None)
        workflow.llm = FakeLLM(
            ['{"route":"OUT_OF_SCOPE","reason":"world knowledge"}']
        )
        state = workflow.invoke(
            application_reference="APP-1",
            request_type="USER_QUERY",
            query="Who is the president?",
        )
        self.assertEqual(state["route"], "OUT_OF_SCOPE")
        self.assertIn("I'm sorry", state["response"]["answer"])

    def test_rag_uses_parent_evidence_and_validates_citations(self):
        retriever = FakeRetriever([parent_evidence()])
        workflow = RagWorkflow(FakeSession(), retriever)
        workflow.embedder = SimpleNamespace(embed_text=lambda text: [0.1])
        workflow.llm = FakeLLM(
            [
                '{"route":"RAG","reason":"document question"}',
                rag_answer(),
            ]
        )
        state = workflow.invoke(
            application_reference="APP-1",
            request_type="USER_QUERY",
            query="What was revenue?",
        )
        self.assertEqual(state["route"], "RAG")
        self.assertEqual(retriever.calls[0]["top_k"], 2)
        self.assertEqual(retriever.calls[0]["candidate_k"], 24)
        self.assertEqual(
            state["response"]["sources"][0]["source_id"],
            "DOC1-CONTENT-101",
        )

    def test_rag_rejects_unknown_citation(self):
        retriever = FakeRetriever([parent_evidence()])
        workflow = RagWorkflow(FakeSession(), retriever)
        workflow.embedder = SimpleNamespace(embed_text=lambda text: [0.1])
        workflow.llm = FakeLLM(
            [
                '{"route":"RAG","reason":"document question"}',
                rag_answer("DOC9-CONTENT-9"),
            ]
        )
        with self.assertRaises(LlmJsonError):
            workflow.invoke(
                application_reference="APP-1",
                request_type="USER_QUERY",
                query="What was revenue?",
            )

    def test_rag_requires_a_citation_when_evidence_exists(self):
        retriever = FakeRetriever([parent_evidence()])
        workflow = RagWorkflow(FakeSession(), retriever)
        workflow.embedder = SimpleNamespace(embed_text=lambda text: [0.1])
        workflow.llm = FakeLLM(
            [
                '{"route":"RAG","reason":"document question"}',
                '{"response_type":"rag_answer","answer":"Revenue was 100.","key_points":[],"sources":[],"limitations":[]}',
            ]
        )
        with self.assertRaises(LlmJsonError):
            workflow.invoke(
                application_reference="APP-1",
                request_type="USER_QUERY",
                query="What was revenue?",
            )

    def test_router_invalid_json_is_not_repaired(self):
        workflow = RagWorkflow(session=None, retriever=None)
        workflow.llm = FakeLLM(["not json"])
        with self.assertRaises(LlmJsonError):
            workflow.invoke(
                application_reference="APP-1",
                request_type="USER_QUERY",
                query="What was revenue?",
            )
        self.assertEqual(len(workflow.llm.prompts), 1)

    def test_credit_memo_route_validates_contract_and_citations(self):
        import json

        payload = {
            "response_type": "credit_memo",
            "borrower_overview": {"text": "Acme.", "source_ids": ["DOC1-CONTENT-101"]},
            "facility_request": {"text": None, "source_ids": []},
            "business_profile": {"text": None, "source_ids": []},
            "financial_analysis": {"text": None, "source_ids": []},
            "key_risks": [],
            "mitigants": [],
            "management_and_governance": {"text": None, "source_ids": []},
            "recommendation": {"text": None, "source_ids": []},
            "missing_information": [],
            "sources": [
                {"source_id": "DOC1-CONTENT-101", "claim": "Borrower name"}
            ],
        }
        retriever = FakeRetriever([parent_evidence()])
        workflow = RagWorkflow(FakeSession(), retriever)
        workflow.embedder = SimpleNamespace(embed_text=lambda text: [0.1])
        workflow.llm = FakeLLM([json.dumps(payload)])
        state = workflow.invoke(
            application_reference="APP-1",
            request_type="CREDIT_MEMO",
            query="Prepare a memo.",
        )
        self.assertEqual(state["response"]["response_type"], "credit_memo")

        payload["borrower_overview"]["source_ids"] = ["DOC9-CONTENT-9"]
        workflow = RagWorkflow(FakeSession(), FakeRetriever([parent_evidence()]))
        workflow.embedder = SimpleNamespace(embed_text=lambda text: [0.1])
        workflow.llm = FakeLLM([json.dumps(payload)])
        with self.assertRaises(LlmJsonError):
            workflow.invoke(
                application_reference="APP-1",
                request_type="CREDIT_MEMO",
                query="Prepare a memo.",
            )


if __name__ == "__main__":
    unittest.main()
