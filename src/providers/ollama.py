"""Ollama (offline) provider via its OpenAI-compatible endpoint."""
from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from src.providers.base import LLMProvider


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str, api_key: str = "ollama") -> None:
        self.model = model
        # Ollama exposes /v1 as an OpenAI-compatible endpoint.
        # api_key is unused server-side but the SDK requires a non-empty value.
        self.client = AsyncOpenAI(api_key=api_key or "ollama", base_url=base_url)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await self.client.chat.completions.create(**kwargs)
        if not response.choices:
            return {"content": "ERROR: empty choices list from provider", "tool_calls": [], "raw": response}
        msg = response.choices[0].message

        tool_calls = []
        for tc in msg.tool_calls or []:
            raw_args = tc.function.arguments
            if isinstance(raw_args, dict):
                args = raw_args
            else:
                try:
                    args = json.loads(raw_args or "{}")
                except (json.JSONDecodeError, TypeError):
                    args = {"_raw": raw_args}
            tool_calls.append(
                {"id": tc.id, "name": tc.function.name, "arguments": args}
            )

        return {
            "content": msg.content,
            "tool_calls": tool_calls,
            "raw": response,
        }
