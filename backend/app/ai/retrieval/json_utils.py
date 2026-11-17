from __future__ import annotations

import json
import re
from typing import Any


class LlmJsonError(ValueError):
    def __init__(self, message: str, raw_preview: str = "") -> None:
        super().__init__(message)
        self.raw_preview = raw_preview


def response_text(response: Any) -> str:
    if isinstance(response, str):
        return response.strip()
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            else:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return str(response or "").strip()


def _first_balanced_object(value: str) -> str | None:
    start = value.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(value)):
        char = value[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return value[start : index + 1]
    return None


def parse_json_object(raw: str) -> dict[str, Any]:
    cleaned = (raw or "").strip()
    if not cleaned:
        raise LlmJsonError("LLM returned an empty response.")
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    candidate = cleaned
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        extracted = _first_balanced_object(cleaned)
        if extracted is None:
            raise LlmJsonError(
                "LLM response did not contain a complete JSON object.",
                cleaned[:500],
            )
        candidate = extracted
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise LlmJsonError(
                "LLM returned malformed JSON at "
                f"line {exc.lineno}, column {exc.colno}: {exc.msg}",
                candidate[:500],
            ) from exc

    if not isinstance(value, dict):
        raise LlmJsonError("LLM JSON response must be an object.", candidate[:500])
    return value
