from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from typing import Any


class CreditMemoCalculationService:
    FORMULAS = {
        "annual_revenue_growth_percent": (
            "revenue",
            "revenue",
            "(current-prior)/prior*100",
        ),
        "gross_margin_percent": ("gross_profit", "revenue", "gross_profit/revenue*100"),
        "operating_margin_percent": (
            "operating_income",
            "revenue",
            "operating_income/revenue*100",
        ),
        "net_profit_margin_percent": (
            "net_profit",
            "revenue",
            "net_profit/revenue*100",
        ),
        "debt_to_equity_ratio": ("debt", "equity", "debt/equity"),
        "current_ratio": (
            "current_assets",
            "current_liabilities",
            "current_assets/current_liabilities",
        ),
    }

    def apply(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        result = deepcopy(payload)
        audit = []
        metrics = list(self._metrics(result))
        by_period = defaultdict(dict)
        for m in metrics:
            if m.get("status") == "available" and isinstance(
                m.get("value"), (int, float)
            ):
                by_period[m.get("period")][m.get("metric_name")] = m
        for metric in metrics:
            if metric.get("status") != "pending_calculation":
                continue
            name = metric.get("metric_name")
            period = metric.get("period")
            formula = self.FORMULAS.get(name)
            if not formula:
                continue
            a = by_period[period].get(formula[0])
            b = by_period[period].get(formula[1])
            if not a or not b or not b.get("value"):
                continue
            value = (
                (a["value"] - b["value"]) / b["value"] * 100
                if name == "annual_revenue_growth_percent"
                else a["value"] / b["value"] * (100 if name.endswith("percent") else 1)
            )
            metric.update(
                status="available",
                value=round(value, 4),
                unit="percent" if name.endswith("percent") else "ratio",
                basis="calculated",
                formula=formula[2],
                evidence=a.get("evidence", []) + b.get("evidence", []),
                notes="Calculated deterministically by application service.",
            )
            audit.append(
                {
                    "metric_name": name,
                    "period": period,
                    "value": metric["value"],
                    "formula": formula[2],
                }
            )
        return result, audit

    def _metrics(self, value: Any):
        if isinstance(value, dict):
            if {"metric_name", "status", "value", "unit", "basis"}.issubset(value):
                yield value
            for v in value.values():
                yield from self._metrics(v)
        elif isinstance(value, list):
            for v in value:
                yield from self._metrics(v)
