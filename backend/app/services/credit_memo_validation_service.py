from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator


class CreditMemoValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors[:8]))


class CreditMemoValidationService:
    def __init__(self, schema_path: Path | None = None):
        self.schema_path = (
            schema_path
            or Path(__file__).resolve().parents[1]
            / "schemas"
            / "credit_memo_output.schema.json"
        )
        self.schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema)

    def validate(
        self, payload: dict[str, Any], *, allowed_source_ids: set[str] | None = None
    ) -> dict[str, Any]:
        errors = [
            f"{'/'.join(str(x) for x in e.absolute_path) or '$'}: {e.message}"
            for e in sorted(
                self.validator.iter_errors(payload), key=lambda x: list(x.absolute_path)
            )
        ]
        if allowed_source_ids is not None:
            for path, source_id in self._evidence_ids(payload):
                if source_id not in allowed_source_ids:
                    errors.append(f"{path}: unknown source_id {source_id}")
        if errors:
            raise CreditMemoValidationError(errors)
        return payload

    def section_errors(self, key: str, value: Any) -> list[str]:
        schema = {
            "$schema": self.schema["$schema"],
            "$defs": self.schema["$defs"],
            **self.schema["properties"][key],
        }
        return [
            f"{'/'.join(str(x) for x in e.absolute_path) or key}: {e.message}"
            for e in Draft202012Validator(schema).iter_errors(value)
        ]

    def _evidence_ids(self, value: Any, path: str = "$"):
        if isinstance(value, dict):
            if set(
                ["source_id", "page_start", "page_end", "section", "locator"]
            ).issubset(value):
                yield path, value["source_id"]
            for k, v in value.items():
                yield from self._evidence_ids(v, f"{path}.{k}")
        elif isinstance(value, list):
            for i, v in enumerate(value):
                yield from self._evidence_ids(v, f"{path}[{i}]")
