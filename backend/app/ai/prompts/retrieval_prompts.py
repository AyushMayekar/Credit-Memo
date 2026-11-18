APPLICATION_CONTEXT = """This application helps credit analysts upload borrower documents,
extract their contents, review reconstructed financial tables, and generate a
grounded credit memo.

It can answer questions about:
- How to upload, parse, review, and ingest documents.
- What document types and reporting periods are supported.
- How the credit-memo workflow, batches, evidence citations, and review flags work.
- The borrower, application, and documents that are currently loaded.

It cannot answer general world-knowledge questions, give personal advice, or
answer questions that are unrelated to the application and its documents."""

OUT_OF_SCOPE_MESSAGE = (
    "I'm sorry, I can only answer questions about this application and the "
    "documents you've uploaded."
)

ROUTER_PROMPT = """Classify the request as exactly one route.

APP_HELP:
High-level questions about the application itself, its workflow, supported
document types, or how to use the product. No document evidence is needed.

OUT_OF_SCOPE:
Questions that are unrelated to this application or its uploaded documents,
including general world knowledge, personal advice, or casual chat.

RAG:
Questions that require evidence from the uploaded borrower documents,
financials, risks, tables, charts, policies, or application records.

CREDIT_MEMO:
Use only when request_type is CREDIT_MEMO.

Application context:
{application_context}

Return JSON only:
{{"route": "APP_HELP|OUT_OF_SCOPE|RAG|CREDIT_MEMO", "reason": "brief reason"}}

Request type: {request_type}
User request: {query}
"""

GENERAL_PROMPT = """You are the assistant for a BFSI credit memo application.

Answer only from the application context below. Do not answer general
world-knowledge questions and do not provide borrower-specific facts.

If the request is outside the application context, return the refusal answer
exactly as provided.

Do not claim to have searched borrower documents, PostgreSQL, or FAISS.

Return JSON only:
{{
  "response_type": "general",
  "answer": "...",
  "sources": [],
  "limitations": []
}}

Application context:
{application_context}

Refusal answer for out-of-scope requests:
""" + OUT_OF_SCOPE_MESSAGE + """

User request:
{query}
"""

RAG_ANSWER_PROMPT = """Answer the question using only the evidence below.

Evidence rules:
- type="PARENT" is narrative section context.
- type="TABLE" is a complete table chunk exactly as stored. Do not shorten,
  filter, or rebuild it before reading it.
- Use row order, column position, periods, units, and numeric cells as the
  primary evidence when a table is supplied.
- Never invent, round, or reassign a numeric value.
- Preserve parentheses as negative values.
- Do not reconstruct or display the table in your answer. Use its values to
  answer the question.
- Cite the supplied source_id exactly for every material statement.
- If the evidence is insufficient, say so clearly.

Return JSON only:
{{
  "response_type": "rag_answer",
  "answer": "grounded answer",
  "key_points": [
    "grounded key point"
  ],
  "sources": [
    {{
      "source_id": "DOC1-CONTENT-123",
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


CREDIT_MEMO_PROMPT = """Create a structured credit memo evidence draft using only
the evidence below.

Evidence rules:
- type="PARENT" is narrative section context.
- type="TABLE" is a complete table chunk exactly as stored.
- You may reconstruct a table inside the memo when the table chunk is supplied.
  Use the chunk exactly as stored as the source of rows, periods, units, and
  numeric values.
- Header and row-label text may be noisy, merged, or repeated. Use row order,
  column position, and numeric cells as the primary evidence.
- Never invent, round, or reassign a numeric value.
- Preserve parentheses as negative values.
- Do not invent missing facts, recommendations, ratios, trends, calculations,
  mitigants, or conclusions.
- Cite the supplied source_id exactly for every material statement.

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
      "source_id": "DOC1-CONTENT-123",
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
