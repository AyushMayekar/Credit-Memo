from __future__ import annotations

from html import escape
import json
from typing import Any

SYSTEM_PROMPT = """You extract one focused credit memo batch.
Use only evidence inside <evidence>. Return one JSON object only.
Follow the exact output contract or action contract. Do not add fields.
Do not infer causes, relationships, ownership, compliance, security or values.
Every material statement must cite supplied source evidence IDs.

Evidence rules:
- type="PARENT" is bounded narrative section context.
- type="TABLE" is a complete table chunk exactly as stored.
- Never shorten, filter, or rebuild a table before reading it.
- Header and row-label text may be noisy; rely on row order, column position,
  periods, units, and numeric cells. Never invent, round, or reassign a numeric
  value. Preserve parentheses as negative values.
- Narrative child chunks are never supplied and must not be requested.
"""


def _tag(name: str, value: Any) -> str:
    return f"<{name}>{escape(str(value or ''))}</{name}>"


def build_output_contract(output) -> dict[str, Any]:
    """
    Validate structure, allowed fields, array sizes and citations.

    Do not use strict character limits for LLM-generated prose.
    Generated wording is shortened safely in Python before validation.
    """
    citation = {
        "type": "string",
        "pattern": "^S\\d+$",
    }
    properties = {
        "status": {
            "type": "string",
            "enum": [
                "available",
                "not_disclosed",
                "conflicting",
                "pending_review",
            ],
        },
        "summary": {
            "type": ["string", "null"],
        },
        "caveats": {
            "type": "array",
            "maxItems": output.max_caveats,
            "items": {
                "type": "string",
            },
        },
        "source_ids": {
            "type": "array",
            "items": citation,
        },
    }

    if output.max_facts:
        properties["facts"] = {
            "type": "array",
            "maxItems": output.max_facts,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "label",
                    "period",
                    "value",
                    "unit",
                    "source_ids",
                ],
                "properties": {
                    "label": {
                        "type": "string",
                    },
                    "period": {
                        "type": ["string", "null"],
                    },
                    "value": {
                        "type": ["number", "null"],
                    },
                    "unit": {
                        "type": "string",
                    },
                    "source_ids": {
                        "type": "array",
                        "items": citation,
                    },
                },
            },
        }

    if output.max_observations:
        properties["observations"] = {
            "type": "array",
            "maxItems": output.max_observations,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "key",
                    "title",
                    "text",
                    "source_ids",
                ],
                "properties": {
                    "key": {
                        "type": "string",
                    },
                    "title": {
                        "type": "string",
                    },
                    "text": {
                        "type": "string",
                    },
                    "source_ids": {
                        "type": "array",
                        "items": citation,
                    },
                },
            },
        }

    if output.max_items:
        properties["items"] = {
            "type": "array",
            "maxItems": output.max_items,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "item_id",
                    "title",
                    "description",
                    "severity",
                    "linked_item_ids",
                    "source_ids",
                    "caveats",
                ],
                "properties": {
                    "item_id": {
                        "type": "string",
                    },
                    "title": {
                        "type": "string",
                    },
                    "description": {
                        "type": "string",
                    },
                    "severity": {
                        "type": "string",
                        "enum": [
                            "low",
                            "medium",
                            "high",
                            "critical",
                            "not_assessed",
                        ],
                    },
                    "linked_item_ids": {
                        "type": "array",
                        "maxItems": 2,
                        "items": {
                            "type": "string",
                        },
                    },
                    "source_ids": {
                        "type": "array",
                        "items": citation,
                    },
                    "caveats": {
                        "type": "array",
                        "maxItems": 1,
                        "items": {
                            "type": "string",
                        },
                    },
                },
            },
        }

    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def _action_contract(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "ANSWER": {
            "action": "ANSWER",
            "answer": contract,
        },
        "FETCH_RELATED_PARENTS": {
            "action": "FETCH_RELATED_PARENTS",
            "reason": "why the related parent is needed",
            "parent_ids": ["one or more ids shown in <related_parents>"],
        },
        "VECTOR_SEARCH": {
            "action": "VECTOR_SEARCH",
            "reason": "why another search is needed",
            "search_query": "reformulated search query",
        },
    }


def _source_xml(item: dict[str, Any], alias: str) -> str:
    kind = item.get("source_type") or item.get("content_type") or ""
    attrs = (
        f'id="{alias}" type="{escape(str(kind))}" '
        f'page="{escape(str(item.get("page") or ""))}" '
        f'document="{escape(str(item.get("document_name") or ""))}" '
        f'section="{escape(str(item.get("section") or ""))}"'
    )
    related = ""
    if kind == "PARENT" and item.get("related_parents"):
        related = "<related_parents>" + "".join(
            f'<related_parent id="{escape(str(value.get("parent_id") or ""))}" '
            f'pages="{escape(str(value.get("pages") or ""))}" '
            f'section="{escape(str(value.get("section_title") or ""))}"/>'
            for value in item["related_parents"]
        ) + "</related_parents>"
    return (
        f"<source {attrs}>{related}"
        f"{escape(str(item.get('text') or ''))}</source>"
    )


def build_batch_messages(
    *,
    batch,
    application_facts: dict,
    evidence: list[dict],
    answer_only: bool = False,
    retry_state: dict[str, Any] | None = None,
    last_error: str | None = None,
) -> tuple[list[dict], dict, dict[str, str]]:
    contract = build_output_contract(batch.output)
    aliases = {f"S{i}": item["source_id"] for i, item in enumerate(evidence, start=1)}
    sources = [
        _source_xml(item, f"S{i}")
        for i, item in enumerate(evidence, start=1)
    ]

    retry_xml = ""
    if retry_state is not None:
        retry_xml = (
            f'<retry_state attempt="{int(retry_state.get("attempt", 0))}" '
            f'max_retries="{int(retry_state.get("max_retries", 0))}" '
            f'answer_only="{str(answer_only).lower()}"/>'
        )

    error_xml = (
        f"<last_error>{escape(last_error)}</last_error>" if last_error else ""
    )

    if answer_only:
        rules = (
            "<rules>"
            "<rule>Use only supplied evidence.</rule>"
            "<rule>Do not calculate missing values.</rule>"
            "<rule>Do not add fields absent from output_contract.</rule>"
            "<rule>Use only the supplied S aliases as citations.</rule>"
            "<rule>This is the final attempt. Return only the answer object. "
            "Do not return an action.</rule>"
            "</rules>"
        )
        contract_xml = (
            "<output_contract>"
            f"{escape(json.dumps(contract, separators=(',', ':')))}"
            "</output_contract>"
        )
    else:
        rules = (
            "<rules>"
            "<rule>Use only supplied evidence.</rule>"
            "<rule>Do not calculate missing values.</rule>"
            "<rule>Return exactly one JSON object matching one action in "
            "action_contract.</rule>"
            "<rule>Use ANSWER when the evidence is sufficient.</rule>"
            "<rule>Use FETCH_RELATED_PARENTS only with ids shown inside "
            "<related_parents>.</rule>"
            "<rule>Use VECTOR_SEARCH only when a different query may find "
            "better evidence.</rule>"
            "<rule>Use only the supplied S aliases as citations.</rule>"
            "</rules>"
        )
        contract_xml = (
            "<action_contract>"
            f"{escape(json.dumps(_action_contract(contract), separators=(',', ':')))}"
            "</action_contract>"
        )

    prompt = "".join(
        [
            "<memo_batch>",
            _tag("section", batch.section_key),
            _tag("batch", batch.key),
            _tag("objective", batch.objective),
            _tag("why_needed", batch.why_needed),
            _tag("audience", batch.audience),
            _tag("query", batch.query),
            "<application>",
            _tag("borrower", application_facts.get("borrower_name")),
            _tag("facility_amount", application_facts.get("facility_amount")),
            _tag("facility_currency", application_facts.get("currency")),
            _tag("tenure_months", application_facts.get("tenure_months")),
            "</application>",
            "<evidence>",
            *sources,
            "</evidence>",
            retry_xml,
            error_xml,
            rules,
            contract_xml,
            "</memo_batch>",
        ]
    )
    return (
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        contract,
        aliases,
    )


def recommendation_contract() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "recommendation_status",
            "recommended_amount",
            "rationale",
            "source_ids",
            "conditions",
            "required_approvals",
            "unresolved_issues",
            "caveats",
        ],
        "properties": {
            "recommendation_status": {
                "type": "string",
                "enum": [
                    "RECOMMENDED",
                    "RECOMMENDED_WITH_CONDITIONS",
                    "NOT_RECOMMENDED",
                    "PENDING_INFORMATION",
                    "PENDING_ANALYST_REVIEW",
                ],
            },
            "recommended_amount": {"type": ["number", "null"]},
            "rationale": {"type": ["string", "null"]},
            "source_ids": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "conditions": {"type": "array", "items": {"type": "string"}},
            "required_approvals": {
                "type": "array",
                "items": {"type": "string"},
            },
            "unresolved_issues": {
                "type": "array",
                "items": {"type": "string"},
            },
            "caveats": {"type": "array", "items": {"type": "string"}},
        },
    }


def build_recommendation_messages(*, digest: dict) -> list[dict]:
    contract = recommendation_contract()
    prompt = "".join(
        [
            "<credit_recommendation>",
            _tag(
                "purpose",
                "Recommend a credit decision for analyst and credit committee review.",
            ),
            f"<decision_digest>{escape(json.dumps(digest, ensure_ascii=False, separators=(',', ':')))}</decision_digest>",
            "<rules><rule>Use only the digest.</rule><rule>Do not repeat company background or application metadata.</rule><rule>Focus only on repayment capacity, key risks, mitigants, security, terms and decision-critical gaps.</rule><rule>Maximum rationale 120 words.</rule><rule>Cite only source_id values that appear in the digest.</rule></rules>",
            "<output_contract>"
            f"{json.dumps(contract, separators=(',', ':'))}"
            "</output_contract>",
            "</credit_recommendation>",
        ]
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
