from __future__ import annotations

from typing import Any

SECTION_TITLES = {
    "borrower_profile": "Borrower Profile",
    "business_and_industry_analysis": "Business and Industry Analysis",
    "management_ownership_governance": "Management, Ownership and Governance",
    "profitability": "Profitability",
    "balance_sheet": "Balance Sheet",
    "cash_flow": "Cash Flow",
    "existing_debt_and_repayment_capacity": "Existing Debt and Repayment Capacity",
    "security_and_collateral": "Security and Collateral",
    "policy_compliance_and_exceptions": "Policy Compliance and Exceptions",
    "proposed_terms_and_conditions": "Proposed Terms and Conditions",
    "executive_summary": "Executive Summary",
}

ITEM_TITLES = {
    "key_credit_strengths": "Key Credit Strengths",
    "key_credit_risks": "Key Credit Risks",
    "risk_mitigants": "Risk Mitigants",
}


class CreditMemoAssemblyService:
    """Convert compact LLM content into the canonical memo schema."""

    def __init__(self, source_lookup: dict[str, dict[str, Any]]) -> None:
        self.source_lookup = source_lookup

    def evidence(self, source_ids: list[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for source_id in dict.fromkeys(str(value) for value in source_ids):
            source = self.source_lookup.get(source_id)
            if source is None:
                continue
            output.append(
                {
                    "source_id": source_id,
                    "page_start": source.get("page_start"),
                    "page_end": source.get("page_end"),
                    "section": source.get("section"),
                    "locator": source.get("locator"),
                }
            )
        return output

    def narrative(
        self,
        *,
        status: str,
        text: str | None,
        source_ids: list[str],
        caveats: list[str],
        analysis_type: str = "source_summary",
    ) -> dict[str, Any]:
        normalized = self._status(status, bool(text))
        return {
            "status": normalized,
            "text": text if normalized == "available" else None,
            "analysis_type": (
                analysis_type if normalized == "available" else "not_applicable"
            ),
            "evidence": self.evidence(source_ids),
            "caveats": [str(item) for item in caveats[:3]],
        }

    def metric(self, fact: dict[str, Any]) -> dict[str, Any]:
        value = fact.get("value")
        available = isinstance(value, (int, float))
        status = self._status(fact.get("status", "available"), available)
        return {
            "metric_name": str(
                fact.get("label") or fact.get("metric_name") or "metric"
            ),
            "period": fact.get("period"),
            "status": status,
            "value": value if available else None,
            "unit": str(fact.get("unit") or "not_specified"),
            "basis": "source_reported" if available else "not_applicable",
            "formula": None,
            "evidence": self.evidence(fact.get("source_ids", [])),
            "notes": fact.get("statement"),
        }

    def standard_section(
        self,
        key: str,
        content: dict[str, Any],
    ) -> dict[str, Any]:
        observations = content.get("observations", [])[:4]
        source_ids = content.get("source_ids", []) or [
            source_id
            for observation in observations
            for source_id in observation.get("source_ids", [])
        ]
        section = {
            "section_key": key,
            "title": SECTION_TITLES[key],
            "status": self._status(content.get("status"), bool(content.get("summary"))),
            "summary": self.narrative(
                status=content.get("status", "not_disclosed"),
                text=content.get("summary"),
                source_ids=source_ids,
                caveats=content.get("caveats", []),
            ),
            "subsections": [],
            "metrics": [self.metric(fact) for fact in content.get("facts", [])[:8]],
            "quality_flags": [],
        }
        for index, observation in enumerate(observations, 1):
            text = observation.get("text")
            section["subsections"].append(
                {
                    "key": observation.get("key") or f"{key}_{index}",
                    "title": observation.get("title") or f"Observation {index}",
                    "status": "available" if text else "not_disclosed",
                    "narrative": self.narrative(
                        status="available" if text else "not_disclosed",
                        text=text,
                        source_ids=observation.get("source_ids", []),
                        caveats=[],
                    ),
                    "metrics": [],
                }
            )
        return section

    def business_section(self, content: dict[str, Any]) -> dict[str, Any]:
        section = self.standard_section("business_and_industry_analysis", content)
        section["operating_segments"] = []
        section["geographic_revenue"] = []
        return section

    def financial_section(
        self,
        *,
        profitability: dict[str, Any],
        balance_sheet: dict[str, Any],
        cash_flow: dict[str, Any],
    ) -> dict[str, Any]:
        children = {
            "profitability": self.standard_section("profitability", profitability),
            "balance_sheet": self.standard_section("balance_sheet", balance_sheet),
            "cash_flow": self.standard_section("cash_flow", cash_flow),
        }
        available = [
            child for child in children.values() if child["status"] == "available"
        ]
        summary_text = (
            " ".join(
                child["summary"]["text"]
                for child in available
                if child["summary"].get("text")
            )[:1800]
            or None
        )
        source_ids = [
            evidence["source_id"]
            for child in available
            for evidence in child["summary"].get("evidence", [])
        ]
        return {
            "section_key": "financial_analysis",
            "title": "Financial Analysis",
            "status": "available" if available else "not_disclosed",
            "summary": self.narrative(
                status="available" if available else "not_disclosed",
                text=summary_text,
                source_ids=source_ids,
                caveats=[],
            ),
            "subsections": [],
            "metrics": [],
            "quality_flags": [],
            **children,
            "ratios": [],
        }

    def item_section(self, key: str, content: dict[str, Any]) -> dict[str, Any]:
        items = []
        for index, item in enumerate(content.get("items", [])[:6], 1):
            items.append(
                {
                    "item_id": item.get("item_id") or f"{key}-{index}",
                    "title": item.get("title") or f"Item {index}",
                    "description": item.get("description") or "",
                    "severity": item.get("severity") or "not_assessed",
                    "linked_item_ids": item.get("linked_item_ids", []),
                    "evidence": self.evidence(item.get("source_ids", [])),
                    "caveats": item.get("caveats", [])[:3],
                }
            )
        source_ids = [
            evidence["source_id"] for item in items for evidence in item["evidence"]
        ]
        return {
            "section_key": key,
            "title": ITEM_TITLES[key],
            "status": "available" if items else "not_disclosed",
            "summary": self.narrative(
                status="available" if items else "not_disclosed",
                text=content.get("summary") if items else None,
                source_ids=source_ids,
                caveats=content.get("caveats", []),
            ),
            "items": items,
            "quality_flags": [],
        }

    def recommendation(
        self,
        content: dict[str, Any],
        *,
        currency: str,
    ) -> dict[str, Any]:
        amount = content.get("recommended_amount")
        available = isinstance(amount, (int, float))
        rationale = content.get("rationale")
        return {
            "section_key": "credit_recommendation",
            "title": "Credit Recommendation",
            "status": "available" if rationale else "pending_review",
            "recommendation_status": content.get(
                "recommendation_status", "PENDING_ANALYST_REVIEW"
            ),
            "recommended_amount": {
                "metric_name": "recommended_amount",
                "period": None,
                "status": "available" if available else "pending_review",
                "value": amount if available else None,
                "unit": f"{currency}_units",
                "basis": "analyst_estimate" if available else "not_applicable",
                "formula": None,
                "evidence": [],
                "notes": "LLM-generated recommendation subject to analyst review.",
            },
            "rationale": self.narrative(
                status="available" if rationale else "pending_review",
                text=rationale,
                source_ids=content.get("source_ids", []),
                caveats=content.get("caveats", []),
                analysis_type="analyst_inference",
            ),
            "conditions": content.get("conditions", [])[:8],
            "required_approvals": content.get("required_approvals", [])[:6],
            "unresolved_issues": content.get("unresolved_issues", [])[:8],
        }

    @staticmethod
    def _status(status: str | None, has_content: bool) -> str:
        allowed = {
            "available",
            "not_disclosed",
            "not_applicable",
            "conflicting",
            "pending_calculation",
            "pending_review",
        }
        if status not in allowed:
            return "available" if has_content else "not_disclosed"
        if status == "available" and not has_content:
            return "not_disclosed"
        return status
