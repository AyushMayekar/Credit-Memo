from __future__ import annotations

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.ai.embedding_model import get_embedding_client
from app.ai.llm import get_llm
from app.ai.prompts.retrieval_prompts import (
    ROUTER_PROMPT,
    GENERAL_PROMPT,
    RAG_ANSWER_PROMPT,
    CREDIT_MEMO_PROMPT,
    retrieval_query,
)
from app.ai.retrieval.faiss_retriever import ApplicationFaissRetriever, RetrievedEvidence
from app.ai.retrieval.section_agent import (
    BatchAgentState,
    run_batch_agent,
    run_all_batches,
)
from app.db.models import LoanApplication


class RetrievalState(TypedDict, total=False):
    application_reference: str
    request_type: str
    query: str
    application_id: int
    borrower_name: str
    route: Literal["GENERAL", "RAG", "CREDIT_MEMO"]
    evidence: list[RetrievedEvidence]
    response: dict[str, Any]


class RagWorkflow:
    """Top-level router + per-batch agent runner.

    Routes:
      - GENERAL → one LLM call, answer immediately.
      - RAG → retrieval + one grounded answer (no retry loops).
      - CREDIT_MEMO → run per-batch agents, combine results.
    """

    def __init__(self, session, retriever: ApplicationFaissRetriever) -> None:
        self.session = session
        self.retriever = retriever
        self.llm = get_llm()
        self.graph = self._build()

    def _build(self):
        graph = StateGraph(RetrievalState)
        graph.add_node("load_application", self._load_application)
        graph.add_node("route", self._route)
        graph.add_node("general_answer", self._general_answer)
        graph.add_node("rag_answer", self._rag_answer)
        graph.add_node("credit_memo", self._credit_memo)
        graph.add_edge(START, "load_application")
        graph.add_edge("load_application", "route")
        graph.add_conditional_edges(
            "route",
            self._route_edge,
            {"GENERAL": "general_answer", "RAG": "rag_answer", "CREDIT_MEMO": "credit_memo"},
        )
        graph.add_edge("general_answer", END)
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
        return {
            "application_id": app.id,
            "borrower_name": app.borrower.legal_name,
        }

    def _route(self, state: RetrievalState):
        """Determine the route: GENERAL, RAG, or CREDIT_MEMO.

        Logic:
          - If request_type == "CREDIT_MEMO" → CREDIT_MEMO
          - If query contains clear financial/borrower terms → RAG
          - If query is short (≤8 words, no document terms) → router LLM
          - Otherwise → RAG
        """
        if state.get("request_type") == "CREDIT_MEMO":
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

        # Short query with no document terms → ask router LLM
        if (
            not any(term in lower for term in document_terms)
            and len(lower.split()) <= 8
        ):
            route_json = self._invoke_router_json(
                ROUTER_PROMPT.format(
                    request_type=state.get("request_type", ""),
                    query=state["query"],
                )
            )
            route = route_json.get("route", "GENERAL")
            # If router says GENERAL, short-circuit with one LLM answer
            if route == "GENERAL":
                return {"route": "GENERAL", "router_reason": route_json.get("reason", "")}
            # If router says CREDIT_MEMO (unlikely for short query but handle)
            if route == "CREDIT_MEMO":
                return {"route": "CREDIT_MEMO"}
            # Otherwise default to RAG
            return {"route": "RAG"}

        # Has document terms → RAG
        return {"route": "RAG"}

    @staticmethod
    def _route_edge(state: RetrievalState) -> Literal["GENERAL", "RAG", "CREDIT_MEMO"]:
        return state["route"]

    def _invoke_router_json(self, prompt: str) -> dict[str, Any]:
        raw = self.llm.invoke(prompt, temperature=0, max_tokens=500)
        try:
            return {"route": raw.get("route"), "reason": raw.get("reason", "")}
        except Exception:
            # Try parse
            import json as _json
            try:
                return _json.loads(raw)
            except Exception:
                return {"route": "GENERAL", "reason": "parse error"}

    def _general_answer(self, state: RetrievalState) -> dict[str, Any]:
        """One-shot GENERAL answer. No retrieval, no second call."""
        prompt = GENERAL_PROMPT.format(query=state["query"])
        raw = self.llm.invoke(prompt, temperature=0, max_tokens=1500)
        # Try parse JSON, fall back to plain text
        import json as _json
        try:
            result = _json.loads(raw)
            return {"response": result}
        except Exception:
            return {"response": {"response_type": "general", "answer": raw.strip(), "sources": [], "limitations": []}}

    def _rag_answer(self, state: RetrievalState) -> dict[str, Any]:
        """One RAG pass: retrieve → LLM answer. No retry loops."""
        borrower = state["borrower_name"]
        application_reference = state["application_reference"]
        query = state["query"]

        # Build embedding
        embedder = get_embedding_client()
        vector = embedder.embed_text(retrieval_query(
            borrower=borrower,
            application_reference=application_reference,
            query=query,
            request_type=state.get("request_type", "USER_QUERY"),
        ))

        # Search FAISS (2 contexts, no retry)
        evidence = self.retriever.search(
            query_vector=vector,
            application_id=state["application_id"],
            top_k=2,
            candidate_k=24,
        )

        # Build evidence text with [1], [2] citations
        evidence_texts = []
        for i, ev in enumerate(evidence, start=1):
            ctx = ev.context_text or ev.text or ""
            evidence_texts.append(f"[{i}] {ctx}")

        evidence_block = "\n\n".join(evidence_texts)

        # LLM answer
        prompt = RAG_ANSWER_PROMPT.format(
            query=query,
            evidence=evidence_block,
        )
        raw = self.llm.invoke(prompt, temperature=0, max_tokens=2000)
        import json as _json
        try:
            result = _json.loads(raw)
            return {"response": result}
        except Exception:
            return {
                "response": {
                    "response_type": "rag_answer",
                    "answer": raw.strip()[:2000],
                    "key_points": [],
                    "sources": [],
                    "limitations": ["failed to parse LLM response"],
                }
            }

    def _credit_memo(self, state: RetrievalState) -> dict[str, Any]:
        """Run per-batch retrieval agents and combine results.

        Each batch runs the bounded agent (max 3 rounds).
        Results are collected and returned for later assembly/combine steps.
        """
        application_reference = state["application_reference"]
        query = state["query"]
        request_type = state.get("request_type", "CREDIT_MEMO")

        # Load application for retriever
        app = self.session.scalar(
            select(LoanApplication).where(
                LoanApplication.application_reference == application_reference
            )
        )
        if app is None:
            raise ValueError("Application not found")

        # We need a retrieper per session; use the injected one with app ID
        # Batch configs (these would normally come from the database/job)
        # For now use the 21 standard batches from the existing defs
        from app.services.credit_memo_batch_definitions import BATCHES

        batch_configs = []
        for batch in BATCHES:
            batch_configs.append(
                {
                    "application_id": app.id,
                    "borrower_name": app.borrower.legal_name,
                    "application_reference": application_reference,
                    "query": query,
                    "request_type": request_type,
                    "batch_key": batch.key,
                    "retriever": self.retriever,
                    # session_factory will be provided by caller
                }
            )

        # Run all batches with 5 concurrent workers
        # Note: session_factory needs to be injected; here we use a closure
        from sqlalchemy.orm import Session

        def session_factory():
            from app.db.session import SessionLocal
            return SessionLocal()

        results = run_all_batches(
            batch_configs=batch_configs,
            session_factory=session_factory,
            max_workers=5,
        )

        # Return structured results for the next stage (assembly/combine)
        return {
            "response": {
                "response_type": "credit_memo_batch",
                "batch_results": results,
                "application_reference": application_reference,
                "query": query,
            }
        }

    def invoke_json(self, prompt: str) -> dict[str, Any]:
        """Helper: invoke LLM and try to parse JSON from the response."""
        raw = self.llm.invoke(prompt, temperature=0, max_tokens=5000)
        import json as _json
        try:
            return _json.loads(raw)
        except Exception:
            # Try extract first balanced object
            depth = 0
            start = -1
            in_string = False
            escaped = False
            for i, ch in enumerate(raw):
                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                    continue
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return _json.loads(raw[start : i + 1])
                        except Exception:
                            return None
            return None


# Convenience standalone function (matches original RagWorkflow.answer_user_query shape)
def answer_user_query(
    session,
    *,
    application_reference: str,
    query: str,
) -> dict[str, Any]:
    """End-user entry point: query an application.

    Returns a dict with route, response, and sources.
    """
    retriever = ApplicationFaissRetriever(session, session.query.__self__.index_path if hasattr(session.query.__self__, 'index_path') else None)
    # We'll build the workflow inline
    from app.ai.retrieval.faiss_manager import FaissIndexManager
    # Get index path from settings-like approach
    from app.core.config import settings
    index_path = settings.resolve_path(settings.faiss_dir) / f"{settings.faiss_index_name}.faiss"
    retriever = ApplicationFaissRetriever(session, index_path)

    workflow = RagWorkflow(session, retriever)
    result = workflow.invoke(
        application_reference=application_reference,
        query=query,
        request_type="USER_QUERY",
    )
    return result
