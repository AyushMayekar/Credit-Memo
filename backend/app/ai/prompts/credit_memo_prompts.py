from __future__ import annotations
from html import escape
import json
from typing import Any

SYSTEM_PROMPT = """You extract one focused credit memo batch.
Use only evidence inside <evidence>. Return one JSON object only.
Follow the exact output contract. Do not add fields.
Do not infer causes, relationships, ownership, compliance, security or values.
Every material statement must cite supplied source aliases.
For reconstructed financial tables, header and row-label text may be noisy;
rely on row order, column position, and numeric cells. Never invent, round, or
reassign a numeric value. Preserve parentheses as negative values.
Keep the answer short. Do not repeat the same point.
"""


def _tag(name: str, value: Any) -> str:
    return f"<{name}>{escape(str(value or ''))}</{name}>"


def build_output_contract(output) -> dict[str, Any]:
    """
    Validate structure, allowed fields, array sizes and citations.

    Do not use strict character limits for LLM-generated prose.
    Generated wording is shortened safely in Python before validation.
    """
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
            "maxItems": 2,
            "items": {
                "type": "string",
                "pattern": "^S[12]$",
            },
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
                        "maxItems": 2,
                        "items": {
                            "type": "string",
                            "pattern": "^S[12]$",
                        },
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
                        "maxItems": 2,
                        "items": {
                            "type": "string",
                            "pattern": "^S[12]$",
                        },
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
                        "maxItems": 2,
                        "items": {
                            "type": "string",
                            "pattern": "^S[12]$",
                        },
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


def build_batch_messages(
    *, batch, application_facts: dict, evidence: list[dict]
) -> tuple[list[dict], dict, dict[str, str]]:
    contract = build_output_contract(batch.output)
    aliases = {f"S{i}": item["source_id"] for i, item in enumerate(evidence, start=1)}
    sources = []
    for i, item in enumerate(evidence, start=1):
        alias = f"S{i}"
        attrs = f'id="{alias}" type="{escape(item["content_type"])}" page="{escape(str(item.get("page") or ""))}" document="{escape(item.get("document_name") or "")}" section="{escape(item.get("section") or "")}"'
        sources.append(f"<source {attrs}>{escape(item['text'])}</source>")
    prompt = "".join(
        [
            "<memo_batch>",
            _tag("section", batch.section_key),
            _tag("batch", batch.key),
            _tag("objective", batch.objective),
            _tag("why_needed", batch.why_needed),
            _tag("audience", batch.audience),
            "<application>",
            _tag("borrower", application_facts.get("borrower_name")),
            _tag("facility_amount", application_facts.get("facility_amount")),
            _tag("facility_currency", application_facts.get("currency")),
            _tag("tenure_months", application_facts.get("tenure_months")),
            "</application>",
            "<evidence>",
            *sources,
            "</evidence>",
            "<rules><rule>Use only supplied evidence.</rule><rule>Do not calculate missing values.</rule><rule>Do not add fields absent from output_contract.</rule><rule>Use only S1 or S2 as citations.</rule><rule>Do not repeat facts in the summary.</rule></rules>",
            f"<output_contract>{escape(json.dumps(contract,separators=(',',':')))}</output_contract>",
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


def build_recommendation_messages(*, digest: dict) -> list[dict]:
    prompt = "".join(
        [
            "<credit_recommendation>",
            _tag(
                "purpose",
                "Recommend a credit decision for analyst and credit committee review.",
            ),
            f"<decision_digest>{escape(json.dumps(digest,ensure_ascii=False,separators=(',',':')))}</decision_digest>",
            "<rules><rule>Use only the digest.</rule><rule>Do not repeat company background or application metadata.</rule><rule>Focus only on repayment capacity, key risks, mitigants, security, terms and decision-critical gaps.</rule><rule>Maximum rationale 120 words.</rule></rules>",
            '<output_contract>{"recommendation_status":"RECOMMENDED|RECOMMENDED_WITH_CONDITIONS|NOT_RECOMMENDED|PENDING_INFORMATION|PENDING_ANALYST_REVIEW","recommended_amount":null,"rationale":"string|null","source_ids":[],"conditions":[],"required_approvals":[],"unresolved_issues":[],"caveats":[]}</output_contract>',
            "</credit_recommendation>",
        ]
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
