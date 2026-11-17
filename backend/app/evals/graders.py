from __future__ import annotations

import json
import math
import re
from typing import Any

from .models import Check

NUMBER_RE = re.compile(r"(?<![A-Za-z])\(?[-+]?\d[\d,]*(?:\.\d+)?%?p?\)?")
MILLION_RE = re.compile(
    r"(?:£|gbp\s*)?\s*\(?([-+]?\d[\d,]*(?:\.\d+)?)\)?\s*(?:m|mn|million)\b",
    re.IGNORECASE,
)
THOUSAND_RE = re.compile(
    r"(?:£|gbp\s*)?\s*\(?([-+]?\d[\d,]*(?:\.\d+)?)\)?\s*(?:k|thousand)\b",
    re.IGNORECASE,
)

NO_ANSWER_PHRASES = (
    "not disclosed",
    "not available",
    "does not contain",
    "does not include",
    "not present in the evidence",
    "insufficient evidence",
    "insufficient information",
    "cannot determine",
    "cannot be determined",
    "cannot calculate",
    "cannot be calculated",
    "cannot be answered",
    "unable to determine",
    "no information about",
    "no information on",
)


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).casefold().strip()


def _plain_number(raw: str) -> float:
    negative = raw.strip().startswith("(") and raw.strip().endswith(")")
    clean = re.sub(r"[,()%p£]", "", raw, flags=re.IGNORECASE).strip("() ")
    value = float(clean)
    return -value if negative else value


def nums(value: Any) -> list[float]:
    """Return raw numbers plus GBP-million values normalized to GBP thousands.

    Examples:
      £17.1m -> 17.1 and 17100
      GBP 17.107 million -> 17.107 and 17107
      £17,107k -> 17107
      (1,234) -> -1234
    """
    text = str(value or "")
    output: list[float] = []

    for raw in NUMBER_RE.findall(text):
        try:
            output.append(_plain_number(raw))
        except ValueError:
            pass

    for match in MILLION_RE.finditer(text):
        try:
            raw = match.group(0)
            value_num = float(match.group(1).replace(",", "")) * 1000.0
            if "(" in raw and ")" in raw:
                value_num *= -1
            output.append(value_num)
        except ValueError:
            pass

    for match in THOUSAND_RE.finditer(text):
        try:
            raw = match.group(0)
            value_num = float(match.group(1).replace(",", ""))
            if "(" in raw and ")" in raw:
                value_num *= -1
            output.append(value_num)
        except ValueError:
            pass

    return output


def num(name: str, expected: float, text: Any, tolerance: float = 0) -> Check:
    found = nums(text)
    passed = any(
        math.isclose(actual, float(expected), abs_tol=tolerance, rel_tol=0)
        for actual in found
    )
    return Check(
        name, passed, f"expected={expected}; tolerance={tolerance}; found={found[:50]}"
    )


def txt(name: str, values: list[str], text: Any) -> Check:
    haystack = norm(text)
    passed = any(norm(value) in haystack for value in values)
    return Check(name, passed, f"expected one of {values}")


def _unit_aliases(unit: str) -> list[str]:
    normalized = norm(unit)
    if normalized in {"£'000", "£’000", "gbp thousands", "gbp_thousands"}:
        return [
            "£'000",
            "£’000",
            "gbp thousands",
            "gbp thousand",
            "£000",
            "£ 000",
            "thousands of pounds",
            "£m",
            "£ m",
            "million pounds",
            "£ million",
        ]
    if normalized in {"£m", "gbp million", "gbp millions"}:
        return [
            "£m",
            "£ m",
            "gbp million",
            "gbp millions",
            "million pounds",
            "£'000",
            "£’000",
        ]
    if normalized == "%":
        return ["%", "percent", "percentage"]
    return [unit]


def retrieval(case: dict[str, Any], selected: list[Any]) -> list[Check]:
    pages = [getattr(item, "page_number", None) for item in selected]
    types = [getattr(item, "content_type", None) for item in selected]

    if case.get("expect_no_answer"):
        page_ok = True
        type_ok = True
    else:
        page_ok = any(page in case["expected_pages"] for page in pages)
        type_ok = any(kind in case["expected_content_types"] for kind in types)

    keys = [
        (
            getattr(item, "content_type", None),
            getattr(item, "parent_content_id", None)
            or getattr(item, "content_id", None),
        )
        for item in selected
    ]

    return [
        Check(
            "selected_expected_page",
            page_ok,
            f"expected={case['expected_pages']}; actual={pages}",
        ),
        Check(
            "expected_content_type",
            type_ok,
            f"expected={case['expected_content_types']}; actual={types}",
        ),
        Check("max_two_contexts", len(selected) <= 2, str(len(selected))),
        Check("distinct_contexts", len(keys) == len(set(keys)), str(keys)),
    ]


def answer(case: dict[str, Any], payload: dict[str, Any]) -> list[Check]:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    answer_text = " ".join(
        [
            str(payload.get("answer") or ""),
            json.dumps(payload.get("limitations") or [], ensure_ascii=False),
        ]
    )
    checks: list[Check] = []

    if case.get("expect_no_answer"):
        honest = any(phrase in norm(answer_text) for phrase in NO_ANSWER_PHRASES)
        checks.append(
            Check(
                "no_answer_honesty",
                honest,
                f"accepted phrases={list(NO_ANSWER_PHRASES)}",
            )
        )

    for fact in case.get("facts", []):
        if isinstance(fact.get("value"), (int, float)):
            checks.append(
                num(
                    "fact:" + fact["name"],
                    fact["value"],
                    text,
                    fact.get("tolerance", 0),
                )
            )
        else:
            checks.append(
                txt(
                    "fact:" + fact["name"],
                    [fact["value"]] + fact.get("aliases", []),
                    text,
                )
            )

        if fact.get("period"):
            checks.append(txt("period:" + fact["name"], [fact["period"]], text))
        if fact.get("unit"):
            checks.append(
                txt(
                    "unit:" + fact["name"],
                    _unit_aliases(fact["unit"]),
                    text,
                )
            )

    sources = payload.get("sources") or []
    checks.append(
        Check(
            "sources_present",
            bool(sources) or case.get("expect_no_answer", False),
            f"count={len(sources)}",
        )
    )
    return checks


def classify(checks: list[Check]):
    failed = {check.name for check in checks if not check.passed}
    if not failed:
        return "PASS", None
    if "selected_expected_page" in failed:
        return "FAIL_RETRIEVAL", "retrieval"
    return "FAIL_GENERATION", "generation"
