ROUTER_PROMPT = """Classify the request as exactly one route:

GENERAL:
Greetings, help, UI usage, or general knowledge that does not require
borrower documents.

RAG:
Questions about the borrower, application, uploaded documents,
financials, risks, tables, charts, policies, or evidence.

CREDIT_MEMO:
Use only when request_type is CREDIT_MEMO.

Return JSON only:
{{"route": "GENERAL|RAG|CREDIT_MEMO", "reason": "brief reason"}}

Request type: {request_type}
User request: {query}
"""


GENERAL_PROMPT = """You are the assistant for a BFSI credit memo
application.

Answer the general user request concisely.

You may explain:
- How to use the credit memo application
- Credit assessment terminology
- General banking and lending concepts

Do not assume the request concerns mortgages.

Do not claim to have searched borrower documents, PostgreSQL, or FAISS.
Do not provide borrower-specific facts unless document evidence was
retrieved through the RAG route.

Return JSON only:
{{
  "response_type": "general",
  "answer": "...",
  "sources": [],
  "limitations": []
}}

User request:
{query}
"""

RAG_ANSWER_PROMPT = """Answer the question using only the two evidence
items provided below.

Elaborate enough to be useful, but do not add unsupported facts,
calculations, conclusions, assumptions, or external knowledge.

If the evidence is insufficient, state that clearly.

When evidence contains a reconstructed financial table:
- Header and row-label text may be noisy, merged, or repeated.
- Use row order, column position, and the numeric cells as the primary evidence.
- Never invent, round, or reassign a numeric value.
- Preserve parentheses as negative values.

Cite evidence using the supplied source_id exactly.

Return JSON only:
{{
  "response_type": "rag_answer",
  "answer": "grounded answer",
  "key_points": [
    "grounded key point"
  ],
  "sources": [
    {{
      "source_id": "SRC-1",
      "claim": "what this source supports"
    }}
  ],
  "limitations": [
    "missing or unsupported information"
  ]
}}

Question:
{query}

Evidence:
{evidence}
"""


CREDIT_MEMO_PROMPT = """Create a structured credit memo evidence draft
using only the two retrieved evidence items.

Do not invent missing facts, recommendations, ratios, trends,
calculations, mitigants, or conclusions.

Use null or empty arrays when information is unsupported.

Every material fact must reference one or more supplied source_ids.

Return JSON only:
{{
  "response_type": "credit_memo",
  "borrower_overview": {{
    "text": null,
    "source_ids": []
  }},
  "facility_request": {{
    "text": null,
    "source_ids": []
  }},
  "business_profile": {{
    "text": null,
    "source_ids": []
  }},
  "financial_analysis": {{
    "text": null,
    "source_ids": []
  }},
  "key_risks": [
    {{
      "risk": "...",
      "source_ids": []
    }}
  ],
  "mitigants": [
    {{
      "mitigant": "...",
      "source_ids": []
    }}
  ],
  "management_and_governance": {{
    "text": null,
    "source_ids": []
  }},
  "recommendation": {{
    "text": null,
    "source_ids": []
  }},
  "missing_information": [
    "unsupported information required to complete the memo"
  ],
  "sources": [
    {{
      "source_id": "SRC-1",
      "claim": "what this source supports"
    }}
  ]
}}

Predefined memo request:
{query}

Evidence:
{evidence}
"""


def retrieval_query(
    *,
    borrower: str,
    application_reference: str,
    query: str,
    request_type: str,
) -> str:
    """Build the contextual text embedded for FAISS query retrieval."""

    return (
        f"Borrower: {borrower}\n"
        f"Application: {application_reference}\n"
        f"Retrieval task: {request_type}\n"
        f"Question: {query}"
    )
