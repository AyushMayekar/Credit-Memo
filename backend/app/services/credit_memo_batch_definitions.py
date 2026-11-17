from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

OutputKind = Literal["facts", "narrative", "items"]


@dataclass(frozen=True, slots=True)
class BatchOutput:
    kind: OutputKind
    summary_words: int = 60
    max_facts: int = 0
    max_observations: int = 0
    max_items: int = 0
    max_caveats: int = 2


@dataclass(frozen=True, slots=True)
class MemoBatch:
    key: str
    section_key: str
    title: str
    objective: str
    why_needed: str
    audience: str
    query: str
    preferred_types: tuple[str, ...]
    output: BatchOutput
    top_k: int = 2
    candidate_k: int = 40
    max_evidence_characters: int = 6500
    max_output_tokens: int = 900


FACTS_2 = BatchOutput("facts", max_facts=2)
NARRATIVE_2 = BatchOutput("narrative", max_observations=2)
ITEMS_2 = BatchOutput("items", max_items=2)

BATCHES = (
    MemoBatch(
        "legal_identity",
        "borrower_profile",
        "Legal identity",
        "Extract legal name, registration number, jurisdiction and entity type.",
        "Confirm the legal borrower.",
        "Credit analyst",
        "legal name registration company number jurisdiction entity type",
        ("CHILD_CHUNK",),
        FACTS_2,
    ),
    MemoBatch(
        "ownership_background",
        "borrower_profile",
        "Ownership and background",
        "Extract confirmed ownership, group structure and operating history. Do not infer relationships from names.",
        "Understand control and operating history.",
        "Credit analyst",
        "ownership shareholders beneficial owners group structure company history",
        ("CHILD_CHUNK",),
        NARRATIVE_2,
    ),
    MemoBatch(
        "business_operations",
        "business_and_industry_analysis",
        "Business operations",
        "Summarize divisions, products, services and end markets.",
        "Understand how the borrower earns money.",
        "Credit analyst",
        "business model divisions products services end markets operations",
        ("CHILD_CHUNK",),
        NARRATIVE_2,
    ),
    MemoBatch(
        "markets_concentration",
        "business_and_industry_analysis",
        "Markets and concentration",
        "Summarize geography, customers, suppliers and concentration only when explicit.",
        "Assess diversification and concentration.",
        "Credit analyst",
        "geographic markets customers suppliers concentration regions",
        ("CHILD_CHUNK", "TABLE_DATA"),
        NARRATIVE_2,
    ),
    MemoBatch(
        "leadership_control",
        "management_ownership_governance",
        "Leadership and control",
        "Extract named directors, management roles and confirmed control facts. Do not infer family control.",
        "Assess management and control.",
        "Credit analyst",
        "directors management chairman ownership control shareholders",
        ("CHILD_CHUNK",),
        NARRATIVE_2,
    ),
    MemoBatch(
        "governance_controls",
        "management_ownership_governance",
        "Governance and controls",
        "Summarize board oversight, audit, committees and internal controls.",
        "Assess the control environment.",
        "Credit analyst",
        "corporate governance audit committee internal controls board oversight",
        ("CHILD_CHUNK",),
        NARRATIVE_2,
    ),
    MemoBatch(
        "revenue_profit",
        "profitability",
        "Revenue and profit",
        "Extract two most decision-useful reported revenue or profit values with periods.",
        "Assess earnings scale and direction.",
        "Credit analyst",
        "revenue operating profit profit before tax profit after tax",
        ("TABLE_DATA",),
        FACTS_2,
        max_evidence_characters=8000,
        max_output_tokens=1000,
    ),
    MemoBatch(
        "margins_returns",
        "profitability",
        "Margins and returns",
        "Extract two most decision-useful reported margin or return values. Do not calculate.",
        "Assess earnings quality and returns.",
        "Credit analyst",
        "gross margin operating margin trading margin ROCE return on capital",
        ("TABLE_DATA", "CHILD_CHUNK"),
        FACTS_2,
        max_evidence_characters=8000,
        max_output_tokens=1000,
    ),
    MemoBatch(
        "assets_equity",
        "balance_sheet",
        "Assets and equity",
        "Extract two most decision-useful reported values for assets, liabilities or equity.",
        "Assess financial position and capital base.",
        "Credit analyst",
        "total assets total liabilities equity net assets balance sheet",
        ("TABLE_DATA",),
        FACTS_2,
        max_evidence_characters=8000,
        max_output_tokens=1000,
    ),
    MemoBatch(
        "liquidity_working_capital",
        "balance_sheet",
        "Liquidity and working capital",
        "Extract two most decision-useful reported values for cash, current assets, current liabilities, receivables or payables. Do not calculate.",
        "Assess short-term liquidity.",
        "Credit analyst",
        "cash current assets current liabilities receivables payables working capital",
        ("TABLE_DATA",),
        FACTS_2,
        max_evidence_characters=8000,
        max_output_tokens=1000,
    ),
    MemoBatch(
        "operating_cash_flow",
        "cash_flow",
        "Operating cash flow",
        "Extract up to two reported operating cash-flow values with periods.",
        "Assess internal cash generation.",
        "Credit analyst",
        "net cash operating activities operating cash flow",
        ("TABLE_DATA",),
        FACTS_2,
        max_evidence_characters=8000,
        max_output_tokens=1000,
    ),
    MemoBatch(
        "capex_financing",
        "cash_flow",
        "Investment and financing cash flow",
        "Extract up to two reported capex, investing or financing values.",
        "Assess reinvestment and external funding.",
        "Credit analyst",
        "capital expenditure investing activities financing activities debt drawdown",
        ("TABLE_DATA",),
        FACTS_2,
        max_evidence_characters=8000,
        max_output_tokens=1000,
    ),
    MemoBatch(
        "debt_liquidity",
        "existing_debt_and_repayment_capacity",
        "Debt and liquidity",
        "Extract up to two reported values for borrowings, net debt, cash or available facilities.",
        "Assess debt burden and liquidity buffer.",
        "Credit analyst",
        "total borrowings net debt cash unutilised facilities liquidity",
        ("TABLE_DATA", "CHILD_CHUNK"),
        FACTS_2,
        max_evidence_characters=8000,
        max_output_tokens=1000,
    ),
    MemoBatch(
        "maturities_capacity",
        "existing_debt_and_repayment_capacity",
        "Maturities and repayment capacity",
        "Extract explicit maturity or repayment-capacity evidence. Do not invent DSCR or EBITDA.",
        "Assess repayment within the facility tenor.",
        "Credit analyst",
        "debt maturities contractual cash flows refinancing repayment capacity DSCR EBITDA",
        ("TABLE_DATA", "CHILD_CHUNK"),
        NARRATIVE_2,
        max_evidence_characters=8000,
    ),
    MemoBatch(
        "existing_security",
        "security_and_collateral",
        "Existing security",
        "Extract disclosed security, collateral, guarantees and charges for existing borrowing.",
        "Understand existing security precedent.",
        "Credit analyst",
        "secured against collateral guarantees charges debenture furnaces land",
        ("CHILD_CHUNK", "TABLE_DATA"),
        NARRATIVE_2,
    ),
    MemoBatch(
        "proposed_security",
        "security_and_collateral",
        "Proposed security",
        "Extract security explicitly linked to the proposed facility. If absent, say so.",
        "Assess lender protection for this facility.",
        "Credit analyst",
        "proposed facility security collateral guarantee charge term sheet",
        ("CHILD_CHUNK",),
        NARRATIVE_2,
    ),
    MemoBatch(
        "credit_strengths",
        "key_credit_strengths",
        "Credit strengths",
        "Identify up to two material evidence-supported credit strengths.",
        "Support a balanced decision.",
        "Credit committee",
        "credit strengths profitability cash flow liquidity diversification controls",
        ("CHILD_CHUNK", "TABLE_DATA"),
        ITEMS_2,
        max_output_tokens=1100,
    ),
    MemoBatch(
        "credit_risks",
        "key_credit_risks",
        "Credit risks",
        "Identify up to two material borrower-specific credit risks and evidence-supported severity.",
        "Identify key downside factors.",
        "Credit committee",
        "credit risks leverage liquidity refinancing concentration market compliance",
        ("CHILD_CHUNK", "TABLE_DATA"),
        ITEMS_2,
        max_output_tokens=1100,
    ),
    MemoBatch(
        "risk_mitigants",
        "risk_mitigants",
        "Risk mitigants",
        "Identify up to two explicit mitigants. Use not_assessed for severity because mitigants are not risks.",
        "Assess protection against key risks.",
        "Credit committee",
        "risk mitigants insurance hedging facilities controls stage payments",
        ("CHILD_CHUNK", "TABLE_DATA"),
        ITEMS_2,
        max_output_tokens=1100,
    ),
    MemoBatch(
        "policy_exceptions",
        "policy_compliance_and_exceptions",
        "Policy and exceptions",
        "Extract lender policy findings only if supplied. Borrower regulatory disclosures are not lender policy compliance.",
        "Identify exceptions requiring approval.",
        "Credit committee",
        "credit policy exception covenant waiver approval threshold",
        ("CHILD_CHUNK",),
        NARRATIVE_2,
    ),
    MemoBatch(
        "proposed_terms",
        "proposed_terms_and_conditions",
        "Proposed terms",
        "Extract proposed pricing, repayment, covenants and conditions. Do not reuse existing borrowing terms.",
        "Define the proposed facility.",
        "Credit committee",
        "proposed facility terms pricing repayment covenants conditions precedent",
        ("CHILD_CHUNK",),
        NARRATIVE_2,
    ),
)
