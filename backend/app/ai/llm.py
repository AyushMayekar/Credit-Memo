from __future__ import annotations

from dataclasses import dataclass

from openai import OpenAI

from app.core.config import settings


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    finish_reason: str | None


class LLMClient:
    def __init__(self) -> None:
        self.client = OpenAI(
            api_key="dummy",
            base_url=settings.llm_base_url,
            default_headers={"x-litellm-api-key": settings.llm_api_key},
            timeout=60.0,
            max_retries=2,
        )

    def chat_response(
        self,
        messages: list[dict],
        temperature: float = 0,
        max_tokens: int = 5000,
    ) -> LLMResponse:
        response = self.client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not response.choices:
            raise ValueError("LLM returned no choices.")
        choice = response.choices[0]
        content = choice.message.content or ""
        if not content.strip():
            raise ValueError("LLM returned an empty response.")
        if choice.finish_reason in {"length", "max_tokens"}:
            raise ValueError("LLM response was truncated before completion.")
        return LLMResponse(content=content, finish_reason=choice.finish_reason)

    def invoke(
        self,
        prompt: str,
        temperature: float = 0,
        max_tokens: int = 5000,
    ) -> str:
        return self.chat_response(
            [{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        ).content


def get_llm() -> LLMClient:
    return LLMClient()
