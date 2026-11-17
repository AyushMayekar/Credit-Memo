import json
from .models import Check
from .graders import num, txt, norm

FACTS = [
    ("FY2024 revenue", 191258, "2024"),
    ("FY2024 trading profit", 24094, "2024"),
    ("FY2024 PBT", 24207, "2024"),
    ("FY2024 cash", 30678, "2024"),
    ("FY2024 net debt", 42931, "2024"),
    ("FY2024 gearing", 35.1, "2024"),
    ("H1 revenue", 106392, "31st October 2024"),
    ("H1 trading profit", 17107, "31st October 2024"),
    ("H1 net debt", 38840, "31st October 2024"),
    ("H1 operating cash", 15412, "31st October 2024"),
]
SECTIONS = [
    "Executive Summary",
    "Borrower Profile",
    "Facility Request",
    "Business and Industry Analysis",
    "Management, Ownership and Governance",
    "Financial Analysis",
    "Existing Debt and Repayment Capacity",
    "Security and Collateral",
    "Key Credit Strengths",
    "Key Credit Risks",
    "Risk Mitigants",
    "Credit Recommendation",
    "Missing Information and Quality Flags",
]


def grade(memo):
    text = json.dumps(memo, ensure_ascii=False, default=str)
    c = [Check("memo_object", isinstance(memo, dict), type(memo).__name__)]
    c += [txt("section:" + s, [s], text) for s in SECTIONS]
    for n, v, p in FACTS:
        c += [num("fact:" + n, v, text), txt("period:" + n, [p], text)]
    h = norm(text)
    c += [
        Check("identity_not_missing", "registered in england and wales" in h),
        Check("security_not_missing", "pledged as security" in h),
        Check(
            "operating_cashflow_not_missing",
            ("net cash from operating activities" in h or "operating cash" in h),
        ),
        Check("no_fake_derivative_drain", "structural liquidity drain" not in h),
    ]
    return c
