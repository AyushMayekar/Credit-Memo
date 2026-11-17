from __future__ import annotations
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class BorrowerCreate(BaseModel):
    legal_name: str
    borrower_type: str = "CORPORATE"
    industry: str | None = None
    country: str | None = None


class FacilityCreate(BaseModel):
    loan_amount: Decimal
    currency: str = "INR"
    loan_purpose: str
    tenure_months: int = Field(gt=0)


class ApplicationCreate(BaseModel):
    borrower: BorrowerCreate
    facility: FacilityCreate


class ApplicationPatch(BaseModel):
    loan_amount: Decimal | None = None
    currency: str | None = None
    loan_purpose: str | None = None
    tenure_months: int | None = None


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    application_reference: str
    status: str
    borrower_name: str
    loan_amount: Decimal
    currency: str
    loan_purpose: str
    tenure_months: int


class JobStartRequest(BaseModel):
    document_ids: list[int] = Field(min_length=1)
    reporting_year: str | None = None


class AiPreparationRequest(BaseModel):
    process_text: bool = True
    process_selected_tables: bool = True
    process_selected_visuals: bool = False
    reporting_year: str | None = None


class SelectionPatch(BaseModel):
    selected_for_analysis: bool
    reason: str | None = None


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)


class MemoRequest(BaseModel):
    template: str = "STANDARD_CREDIT_MEMO"


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    job_reference: str
    job_type: str
    status: str
    progress_percentage: int
    current_stage: str
    current_stage_label: str
    message: str | None
    stage_details: list[Any]
    result_payload: dict[str, Any]
    error_message: str | None
