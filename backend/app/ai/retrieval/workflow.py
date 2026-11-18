from __future__ import annotations

from typing import Any, Literal, TypedDict

from jsonschema import Draft202012Validator
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.embedding_model import get_embedding_client
from app.ai.llm import get_llm
from app.ai.prompts.retrieval_prompts import (
    APPLICATION_CONTEXT,
    CREDIT_MEMO_PROMPT,
    GENERAL_PROMPT,
    OUT_OF_SCOPE_MESSAGE,
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


CREDIT_MEMO_CONTRACT = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "response_type",
        "borrower_overview",
        "facility_request",
        "business_profile",
        "financial_analysis",
        "key_risks",
        "mitigants",
        "management_and_governance",
        "recommendation",
        "missing_information",
        "sources",
    ],
    "properties": {
        "response_type": {"const": "credit_memo"},
        "borrower_overview": {"$ref": "#/$defs/textBlock"},
        "facility_request": {"$ref": "#/$defs/textBlock"},
        "business_profile": {"$ref": "#/$defs/textBlock"},
        "financial_analysis": {"$ref": "#/$defs/textBlock"},
        "management_and_governance": {"$ref": "#/$defs/textBlock"},
        "recommendation": {"$ref": "#/$defs/textBlock"},
        "key_risks": {
            "type": "array",
            "items": {"$ref": "#/$defs/riskItem"},
        },
        "mitigants": {
            "type": "array",
            "items": {"$ref": "#/$defs/mitigantItem"},
        },
        "missing_information": {
            "type": "array",
            "items": {"type": "string"},
        },
        "sources": {
            "type": "array",
            "items": {"$ref": "#/$defs/sourceItem"},
        },
    },
    "$defs": {
        "textBlock": {
            "type": "object",
            "additionalProperties": False,
            "required": ["text", "source_ids"],
            "properties": {
                "text": {"type": ["string", "null"]},
                "source_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        "riskItem": {
            "type": "object",
            "additionalProperties": False,
            "required": ["risk", "source_ids"],
            "properties": {
                "risk": {"type": "string"},
                "source_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        "mitigantItem": {
            "type": "object",
            "additionalProperties": False,
            "required": ["mitigant", "source_ids"],
            "properties": {
                "mitigant": {"type": "string"},
                "source_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        "sourceItem": {
            "type": "object",
            "additionalProperties": False,
            "required": ["source_id", "claim"],
            "properties": {
                "source_id": {"type": "string", "minLength": 1},
                "claim": {"type": "string"},
            },
        },
    },
}

GENERAL_CONTRACT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["response_type", "answer", "sources", "limitations"],
    "properties": {
        "response_type": {"const": "general"},
        "answer": {"type": "string", "minLength": 1},
        "sources": {"type": "array", "maxItems": 0},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
}

RAG_CONTRACT = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "response_type",
        "answer",
        "key_points",
        "sources",
        "limitations",
    ],
    "properties": {
        "response_type": {"const": "rag_answer"},
        "answer": {"type": "string", "minLength": 1},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_id", "claim"],
                "properties": {
                    "source_id": {"type": "string", "minLength": 1},
                    "claim": {"type": "string", "minLength": 1},
                },
            },
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
}


class RagWorkflow:
    FINAL_PARENT_CONTEXTS = 2
    CHILD_CANDIDATES = 24
    ROUTES = {"APP_HELP", "OUT_OF_SCOPE", "RAG", "CREDIT_MEMO"}

    def __init__(self, session: Session, retriever: ApplicationFaissRetriever) -> None:
        self.session = session
        self.retriever = retriever
        self.llm = get_llm()
        self.embedder = get_embedding_client()
        self.graph = self._build()

    def _build(self):
        graph = StateGraph(RetrievalState)
        graph.add_node("route", self._route)
        graph.add_node("general", self._general)
        graph.add_node("out_of_scope", self._out_of_scope)
        graph.add_node("load_application", self._load_application)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("rag_answer", self._rag_answer)
        graph.add_node("credit_memo", self._credit_memo)

        graph.add_edge(START, "route")
        graph.add_conditional_edges(
            "route",
            self._route_edge,
            {
                "APP_HELP": "general",
                "OUT_OF_SCOPE": "out_of_scope",
                "RAG": "load_application",
                "CREDIT_MEMO": "load_application",
            },
        )
        graph.add_edge("load_application", "retrieve")
        graph.add_conditional_edges(
            "retrieve",
            self._after_retrieve,
            {"RAG": "rag_answer", "CREDIT_MEMO": "credit_memo"},
        )
        graph.add_edge("general", END)
        graph.add_edge("out_of_scope", END)
        graph.add_edge("rag_answer", END)
        graph.add_edge("credit_memo", END)
        return graph.compile()

    def invoke(self, **state: Any) -> dict[str, Any]:
        return self.graph.invoke(state)

    def _route(self, state: RetrievalState):
        if state["request_type"] == "CREDIT_MEMO":
            return {"route": "CREDIT_MEMO"}

        route = self._invoke_json(
            ROUTER_PROMPT.format(
                application_context=APPLICATION_CONTEXT,
                request_type=state["request_type"],
                query=state["query"],
            )
        ).get("route", "OUT_OF_SCOPE")
        if route not in self.ROUTES or route == "CREDIT_MEMO":
            route = "OUT_OF_SCOPE"
        return {"route": route}

    @staticmethod
    def _route_edge(
        state: RetrievalState,
    ) -> Literal["APP_HELP", "OUT_OF_SCOPE", "RAG", "CREDIT_MEMO"]:
        return state["route"]

    @staticmethod
    def _after_retrieve(state: RetrievalState) -> Literal["RAG", "CREDIT_MEMO"]:
        return state["route"]

    def _load_application(self, state: RetrievalState):
        app = self.session.scalar(
            select(LoanApplication).where(
                LoanApplication.application_reference == state["application_reference"]
            )
        )
        if app is None:
            raise ValueError("Application not found")
        return {"application_id": app.id, "borrower_name": app.borrower.legal_name}

    def _general(self, state: RetrievalState):
        response = self._invoke_json(
            GENERAL_PROMPT.format(
                application_context=APPLICATION_CONTEXT,
                query=state["query"],
            )
        )
        self._validate_contract(response, GENERAL_CONTRACT, label="General answer")
        return {"response": response}

    def _out_of_scope(self, state: RetrievalState):
        return {
            "response": {
                "response_type": "general",
                "answer": OUT_OF_SCOPE_MESSAGE,
                "sources": [],
                "limitations": [],
            }
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
        response = self._invoke_json(prompt)
        self._validate_contract(response, RAG_CONTRACT, label="RAG answer")
        evidence = state.get("evidence", [])
        if (
            evidence
            and not response.get("sources")
            and not response.get("limitations")
        ):
            raise LlmJsonError(
                "RAG answer did not cite any supplied evidence."
            )
        allowed = {item.source_id for item in evidence}
        unknown = [
            source.get("source_id")
            for source in response.get("sources", [])
            if source.get("source_id") not in allowed
        ]
        if unknown:
            raise LlmJsonError(
                "RAG answer cited unknown source IDs: "
                + ", ".join(sorted(set(str(value) for value in unknown))[:4])
            )
        return {"response": response}

    def _credit_memo(self, state: RetrievalState):
        prompt = CREDIT_MEMO_PROMPT.format(
            query=state["query"],
            evidence=self._evidence_text(state.get("evidence", [])),
        )
        response = self._invoke_json(prompt)
        self._validate_contract(
            response, CREDIT_MEMO_CONTRACT, label="Credit memo"
        )
        allowed = {item.source_id for item in state.get("evidence", [])}
        unknown = [
            source_id
            for source_id in self._collect_source_ids(response)
            if source_id not in allowed
        ]
        if unknown:
            raise LlmJsonError(
                "Credit memo cited unknown source IDs: "
                + ", ".join(sorted(set(unknown))[:4])
            )
        return {"response": response}

    @staticmethod
    def _collect_source_ids(value: Any) -> list[str]:
        output: list[str] = []
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "source_ids" and isinstance(item, list):
                    output.extend(str(source_id) for source_id in item)
                elif key == "source_id" and isinstance(item, str):
                    output.append(item)
                else:
                    output.extend(RagWorkflow._collect_source_ids(item))
        elif isinstance(value, list):
            for item in value:
                output.extend(RagWorkflow._collect_source_ids(item))
        return output

    def _invoke_json(self, prompt: str) -> dict[str, Any]:
        # RAG, general-help, and routing are deliberately zero-retry paths.
        # Invalid JSON is surfaced to the API instead of repaired with another
        # LLM call.
        return parse_json_object(self.llm.invoke(prompt))

    @staticmethod
    def _validate_contract(
        payload: dict[str, Any],
        contract: dict[str, Any],
        *,
        label: str,
    ) -> None:
        errors = [
            (
                f"{'/'.join(str(value) for value in error.absolute_path) or '$'}: "
                f"{error.message}"
            )
            for error in Draft202012Validator(contract).iter_errors(payload)
        ]
        if errors:
            raise LlmJsonError(
                f"{label} returned invalid output: " + "; ".join(errors[:5])
            )

    @staticmethod
    def _evidence_text(items: list[RetrievedEvidence]) -> str:
        if not items:
            return "No evidence retrieved."
        blocks = []
        for item in items:
            if item.content_type not in {"PARENT_SECTION", "TABLE_DATA"}:
                continue
            pages = (
                str(item.page_number)
                if item.page_number == item.page_end
                else f"{item.page_number}-{item.page_end}"
            )
            blocks.append(
                f"[{item.source_id}] type={item.content_type}; "
                f"pages={pages}; section={item.section_title}; "
                f"source={item.source_reference}\n"
                f"{item.text}"
            )
        return "\n\n".join(blocks) if blocks else "No evidence retrieved."
