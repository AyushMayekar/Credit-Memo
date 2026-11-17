from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import CreditMemo, LoanApplication, RagGeneration
from app.services.credit_memo_assembly_service import CreditMemoAssemblyService
from app.services.credit_memo_batch_combiner import CreditMemoBatchCombiner
from app.services.credit_memo_calculation_service import CreditMemoCalculationService
from app.services.credit_memo_extraction_service import CreditMemoExtractionService
from app.services.credit_memo_validation_service import CreditMemoValidationService
from app.ai.retrieval.section_retriever import RetrievalRequest
from app.core.config import settings


@dataclass(frozen=True, slots=True)
class CreditMemoGenerationResult:
    memo_id: int
    version_number: int
    memo_status: str
    memo_content: dict[str, Any]
    source_count: int
    quality_status: str


@dataclass(frozen=True, slots=True)
class CanonicalMemoBuildResult:
    application: LoanApplication
    version_number: int
    payload: dict[str, Any]
    batches: Any
    extracted: dict[str, Any]
    audit: Any
    filtered_sources: dict[str, Any]
    calculation_audit: Any


class UniversalCreditMemoGenerationService:
    PROMPT_VERSION = "CREDIT_MEMO_BATCH_XML_V5"

    def __init__(self, session: Session):
        self.session = session
        self.extractor = CreditMemoExtractionService()
        self.validator = CreditMemoValidationService()
        self.calculator = CreditMemoCalculationService()

    def generate(
        self,
        *,
        application_reference: str,
    ) -> CreditMemoGenerationResult:
        application = self._get_application(
            application_reference=application_reference,
        )

        previous_status = application.status
        application.status = "GENERATING_MEMO"
        self.session.commit()

        try:
            build_result = self._build_canonical_memo(
                application=application,
            )

            return self._persist_memo(
                build_result=build_result,
            )

        except Exception:
            self.session.rollback()

            current_application = self.session.get(
                LoanApplication,
                application.id,
            )

            if current_application is not None:
                current_application.status = previous_status
                self.session.commit()

            raise

    def generate_read_only(
        self,
        *,
        application_reference: str,
    ) -> dict[str, Any]:
        application = self._get_application(
            application_reference=application_reference,
        )

        build_result = self._build_canonical_memo(
            application=application,
        )

        return build_result.payload

    def _get_application(
        self,
        *,
        application_reference: str,
    ) -> LoanApplication:
        application = self.session.scalar(
            select(LoanApplication).where(
                LoanApplication.application_reference == application_reference
            )
        )

        if application is None:
            raise ValueError("Application not found.")

        if application.status not in {
            "AI_READY",
            "MEMO_READY",
            "GENERATING_MEMO",
        }:
            raise ValueError(
                "Application must be AI_READY or MEMO_READY " "before memo generation."
            )

        return application

    def _build_canonical_memo(
        self,
        *,
        application: LoanApplication,
    ) -> CanonicalMemoBuildResult:
        version_number = (
            int(
                self.session.scalar(
                    select(func.max(CreditMemo.version_number)).where(
                        CreditMemo.application_id == application.id
                    )
                )
                or 0
            )
            + 1
        )

        facts = self._application_facts(application)

        request = RetrievalRequest(
            application.id,
            application.application_reference,
            application.borrower.legal_name,
        )

        batches, sources, audit = self.extractor.extract_all(
            request=request,
            application_facts=facts,
        )

        extracted = CreditMemoBatchCombiner().combine(batches)

        assembler = CreditMemoAssemblyService(sources)

        sections = {
            "borrower_profile": assembler.standard_section(
                "borrower_profile",
                extracted["borrower_profile"],
            ),
            "business_and_industry_analysis": (
                assembler.business_section(extracted["business_and_industry_analysis"])
            ),
            "management_ownership_governance": (
                assembler.standard_section(
                    "management_ownership_governance",
                    extracted["management_ownership_governance"],
                )
            ),
            "financial_analysis": assembler.financial_section(
                profitability=extracted["profitability"],
                balance_sheet=extracted["balance_sheet"],
                cash_flow=extracted["cash_flow"],
            ),
            "existing_debt_and_repayment_capacity": (
                assembler.standard_section(
                    "existing_debt_and_repayment_capacity",
                    extracted["existing_debt_and_repayment_capacity"],
                )
            ),
            "security_and_collateral": (
                assembler.standard_section(
                    "security_and_collateral",
                    extracted["security_and_collateral"],
                )
            ),
            "key_credit_strengths": assembler.item_section(
                "key_credit_strengths",
                extracted["key_credit_strengths"],
            ),
            "key_credit_risks": assembler.item_section(
                "key_credit_risks",
                extracted["key_credit_risks"],
            ),
            "risk_mitigants": assembler.item_section(
                "risk_mitigants",
                extracted["risk_mitigants"],
            ),
            "policy_compliance_and_exceptions": (
                assembler.standard_section(
                    "policy_compliance_and_exceptions",
                    extracted["policy_compliance_and_exceptions"],
                )
            ),
            "proposed_terms_and_conditions": (
                assembler.standard_section(
                    "proposed_terms_and_conditions",
                    extracted["proposed_terms_and_conditions"],
                )
            ),
        }

        sections["executive_summary"] = self._executive_summary(
            assembler,
            sections,
        )

        digest = self._decision_digest(
            facts,
            extracted,
        )

        recommendation = self.extractor.recommend(
            digest=digest,
            allowed_source_ids=set(sources),
        )

        sections["credit_recommendation"] = assembler.recommendation(
            recommendation,
            currency=application.currency,
        )

        referenced_source_ids = self._referenced_source_ids(sections)

        filtered_sources = {
            source_id: source
            for source_id, source in sources.items()
            if source_id in referenced_source_ids
        }

        payload = {
            "schema_version": "2.0.0",
            "report_metadata": {
                "report_title": (f"{application.borrower.legal_name} " "Credit Memo"),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "language": "en",
                "display_currency": application.currency,
                "period_label": self._period_label(application),
                "application_reference": (application.application_reference),
                "memo_version": version_number,
            },
            **sections,
            "facility_request": self._facility(application),
            "missing_information_and_quality_flags": (self._quality(sections)),
            "source_register": list(filtered_sources.values()),
            "generation_metadata": {
                "model": settings.llm_model,
                "prompt_version": self.PROMPT_VERSION,
                "generation_mode": ("parallel_xml_batches"),
                "audit": audit,
                "calculation_audit": [],
            },
        }

        payload, calculation_audit = self.calculator.apply(payload)

        payload["generation_metadata"]["calculation_audit"] = calculation_audit

        self.validator.validate(
            payload,
            allowed_source_ids=set(filtered_sources),
        )

        return CanonicalMemoBuildResult(
            application=application,
            version_number=version_number,
            payload=payload,
            batches=batches,
            extracted=extracted,
            audit=audit,
            filtered_sources=filtered_sources,
            calculation_audit=calculation_audit,
        )

    def _persist_memo(
        self,
        *,
        build_result: CanonicalMemoBuildResult,
    ) -> CreditMemoGenerationResult:
        application = build_result.application
        payload = build_result.payload

        memo = CreditMemo(
            application_id=application.id,
            version_number=build_result.version_number,
            memo_status="DRAFT",
            memo_content=payload,
            schema_version="2.0.0",
            raw_generation_json={
                "batch_results": build_result.batches,
                "combined_content": (build_result.extracted),
                "audit": build_result.audit,
            },
            validation_report={
                "valid": True,
                "errors": [],
                "calculation_audit": (build_result.calculation_audit),
            },
            generated_by_model=settings.llm_model,
            prompt_version=self.PROMPT_VERSION,
        )

        self.session.add(memo)
        self.session.flush()

        generation_record = RagGeneration(
            application_id=application.id,
            request_type="CREDIT_MEMO",
            route="PARALLEL_XML_BATCH_RAG",
            user_query=None,
            predefined_prompt_key=self.PROMPT_VERSION,
            response_json=payload,
            source_snapshot=list(build_result.filtered_sources.values()),
            status="COMPLETED",
        )

        self.session.add(generation_record)

        application.status = "MEMO_READY"

        self.session.commit()
        self.session.refresh(memo)

        quality_status = payload["missing_information_and_quality_flags"][
            "overall_quality_status"
        ]

        return CreditMemoGenerationResult(
            memo_id=memo.id,
            version_number=build_result.version_number,
            memo_status=memo.memo_status,
            memo_content=payload,
            source_count=len(build_result.filtered_sources),
            quality_status=quality_status,
        )

    @staticmethod
    def _decision_digest(facts, extracted):
        def compact(key):
            value = extracted.get(key, {})
            return {
                "status": value.get("status"),
                "summary": value.get("summary"),
                "facts": value.get("facts", [])[:6],
                "items": value.get("items", [])[:5],
                "caveats": value.get("caveats", [])[:3],
            }

        return {
            "facility": {
                "amount": facts["facility_amount"],
                "currency": facts["currency"],
                "tenure_months": facts["tenure_months"],
            },
            "profitability": compact("profitability"),
            "balance_sheet": compact("balance_sheet"),
            "cash_flow": compact("cash_flow"),
            "debt_and_capacity": compact("existing_debt_and_repayment_capacity"),
            "strengths": compact("key_credit_strengths"),
            "risks": compact("key_credit_risks"),
            "mitigants": compact("risk_mitigants"),
            "security": compact("security_and_collateral"),
            "terms": compact("proposed_terms_and_conditions"),
        }

    @staticmethod
    def _referenced_source_ids(value):
        found = set()

        def walk(node):
            if isinstance(node, dict):
                if "source_id" in node:
                    found.add(node["source_id"])
                for item in node.values():
                    walk(item)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(value)
        return found

    @staticmethod
    def _executive_summary(assembler, sections):
        parts = []
        source_ids = []
        for key in (
            "business_and_industry_analysis",
            "financial_analysis",
            "existing_debt_and_repayment_capacity",
            "key_credit_risks",
        ):
            summary = sections[key].get("summary", {})
            if summary.get("status") == "available" and summary.get("text"):
                first_sentence = summary["text"].split(". ", 1)[0].rstrip(".") + "."
                parts.append(first_sentence)
                source_ids.extend(
                    e["source_id"] for e in summary.get("evidence", [])[:2]
                )
        text = " ".join(parts[:4]) or None
        return {
            "section_key": "executive_summary",
            "title": "Executive Summary",
            "status": "available" if text else "not_disclosed",
            "summary": assembler.narrative(
                status="available" if text else "not_disclosed",
                text=text,
                source_ids=source_ids,
                caveats=[],
            ),
            "subsections": [],
            "metrics": [],
            "quality_flags": [],
        }

    @staticmethod
    def _application_facts(a):
        return {
            "borrower_name": a.borrower.legal_name,
            "facility_amount": float(a.loan_amount),
            "currency": a.currency,
            "tenure_months": a.tenure_months,
            "purpose": a.loan_purpose,
        }

    @staticmethod
    def _facility(a):
        return {
            "section_key": "facility_request",
            "title": "Facility Request",
            "status": "available",
            "summary": {
                "status": "available",
                "text": f"Requested {a.currency} {a.loan_amount:,.2f} for a tenure of {a.tenure_months} months.",
                "analysis_type": "source_summary",
                "evidence": [],
                "caveats": ["Application-entered facility details."],
            },
            "subsections": [],
            "metrics": [
                {
                    "metric_name": "requested_facility_amount",
                    "period": None,
                    "status": "available",
                    "value": float(a.loan_amount),
                    "unit": a.currency,
                    "basis": "source_reported",
                    "formula": None,
                    "evidence": [],
                    "notes": "Application-entered amount.",
                },
                {
                    "metric_name": "requested_tenure_months",
                    "period": None,
                    "status": "available",
                    "value": a.tenure_months,
                    "unit": "months",
                    "basis": "source_reported",
                    "formula": None,
                    "evidence": [],
                    "notes": "Application-entered tenure.",
                },
            ],
            "quality_flags": [],
        }

    @staticmethod
    def _period_label(a):
        years = sorted(
            {c.reporting_year for c in a.document_contents if c.reporting_year}
        )
        return ", ".join(years) if years else "Reviewed reporting periods"

    @staticmethod
    def _quality(sections):
        labels = {
            key: value.get("title", key.replace("_", " ").title())
            for key, value in sections.items()
        }
        missing = [
            labels[key]
            for key, value in sections.items()
            if value.get("status") == "not_disclosed"
        ]
        review = [
            labels[key]
            for key, value in sections.items()
            if value.get("status") == "pending_review"
        ]
        return {
            "missing_information": missing,
            "conflicts": [],
            "pending_calculations": [],
            "review_items": review,
            "overall_quality_status": (
                "requires_review"
                if review
                else "usable_with_caveats" if missing else "complete"
            ),
        }
