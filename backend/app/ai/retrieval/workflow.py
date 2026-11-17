from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.embedding_model import get_embedding_client
from app.ai.llm import get_llm
from app.ai.prompts.retrieval_prompts import (
    CREDIT_MEMO_PROMPT,
    GENERAL_PROMPT,
    RAG_ANSWER_PROMPT,
    ROUTER_PROMPT,
    retrieval_query,
)
from app.ai.retrieval.faiss_retriever import (
    ApplicationFaissRetriever,
    RetrievedEvidence,
)
from app.ai.retrieval.json_utils import LlmJsonError, parse_json_object
from app.db.models import LoanApplication


class RetrievalState(TypedDict, total=False):
    application_reference: str
    request_type: str
    query: str
    application_id: int
    borrower_name: str
    route: str
    evidence: list[RetrievedEvidence]
    response: dict[str, Any]


class RagWorkflow:
    FINAL_PARENT_CONTEXTS = 2
    CHILD_CANDIDATES = 24

    def __init__(self, session: Session, retriever: ApplicationFaissRetriever) -> None:
        self.session = session
        self.retriever = retriever
        self.llm = get_llm()
        self.embedder = get_embedding_client()
        self.graph = self._build()

    def _build(self):
        graph = StateGraph(RetrievalState)
        graph.add_node("load_application", self._load_application)
        graph.add_node("route", self._route)
        graph.add_node("general", self._general)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("rag_answer", self._rag_answer)
        graph.add_node("credit_memo", self._credit_memo)
        graph.add_edge(START, "load_application")
        graph.add_edge("load_application", "route")
        graph.add_conditional_edges(
            "route",
            self._route_edge,
            {"GENERAL": "general", "RAG": "retrieve", "CREDIT_MEMO": "retrieve"},
        )
        graph.add_conditional_edges(
            "retrieve",
            self._after_retrieve,
            {"RAG": "rag_answer", "CREDIT_MEMO": "credit_memo"},
        )
        graph.add_edge("general", END)
        graph.add_edge("rag_answer", END)
        graph.add_edge("credit_memo", END)
        return graph.compile()

    def invoke(self, **state: Any) -> dict[str, Any]:
        return self.graph.invoke(state)

    def _load_application(self, state: RetrievalState):
        app = self.session.scalar(
            select(LoanApplication).where(
                LoanApplication.application_reference == state["application_reference"]
            )
        )
        if app is None:
            raise ValueError("Application not found")
        return {"application_id": app.id, "borrower_name": app.borrower.legal_name}

    def _route(self, state: RetrievalState):
        if state["request_type"] == "CREDIT_MEMO":
            return {"route": "CREDIT_MEMO"}
        lower = state["query"].casefold()
        document_terms = (
            "revenue",
            "profit",
            "risk",
            "borrower",
            "company",
            "document",
            "report",
            "financial",
            "table",
            "chart",
            "director",
            "application",
            "loan",
        )
        if (
            not any(term in lower for term in document_terms)
            and len(lower.split()) <= 8
        ):
            route = self._invoke_json(
                ROUTER_PROMPT.format(
                    request_type=state["request_type"], query=state["query"]
                )
            ).get("route", "GENERAL")
        else:
            route = "RAG"
        return {"route": route if route in {"GENERAL", "RAG"} else "RAG"}

    @staticmethod
    def _route_edge(state: RetrievalState) -> Literal["GENERAL", "RAG", "CREDIT_MEMO"]:
        return state["route"]

    @staticmethod
    def _after_retrieve(state: RetrievalState) -> Literal["RAG", "CREDIT_MEMO"]:
        return state["route"]

    def _general(self, state: RetrievalState):
        return {
            "response": self._invoke_json(GENERAL_PROMPT.format(query=state["query"]))
        }

    def _retrieve(self, state: RetrievalState):
        enriched = retrieval_query(
            borrower=state["borrower_name"],
            application_reference=state["application_reference"],
            query=state["query"],
            request_type=state["request_type"],
        )
        vector = self.embedder.embed_text(enriched)
        evidence = self.retriever.search(
            query_vector=vector,
            application_id=state["application_id"],
            top_k=self.FINAL_PARENT_CONTEXTS,
            candidate_k=self.CHILD_CANDIDATES,
        )
        return {"evidence": evidence}

    def _rag_answer(self, state: RetrievalState):
        prompt = RAG_ANSWER_PROMPT.format(
            query=state["query"],
            evidence=self._evidence_text(state.get("evidence", [])),
        )
        return {"response": self._invoke_json(prompt)}

    def _credit_memo(self, state: RetrievalState):
        prompt = CREDIT_MEMO_PROMPT.format(
            query=state["query"],
            evidence=self._evidence_text(state.get("evidence", [])),
        )
        return {"response": self._invoke_json(prompt)}

    def _invoke_json(self, prompt: str) -> dict[str, Any]:
        raw = self.llm.invoke(prompt)
        try:
            return parse_json_object(raw)
        except LlmJsonError:
            repair_prompt = (
                "Convert the response below into one valid JSON object only. "
                "Preserve its meaning. Do not add facts. Do not use Markdown.\n\n"
                f"RESPONSE TO REPAIR:\n{raw[:12000]}"
            )
            repaired = self.llm.invoke(repair_prompt, max_tokens=5000)
            return parse_json_object(repaired)

    @staticmethod
    def _evidence_text(items: list[RetrievedEvidence]) -> str:
        if not items:
            return "No evidence retrieved."
        blocks = []
        for item in items:
            pages = (
                str(item.page_number)
                if item.page_number == item.page_end
                else f"{item.page_number}-{item.page_end}"
            )
            blocks.append(
                f"[{item.source_id}] citation_type={item.content_type}; "
                f"citation_pages={pages}; section={item.section_title}; "
                f"source={item.source_reference}; retrieved_child={item.text}; "
                f"parent_context={item.context_text}"
            )
        return "\n\n".join(blocks)
