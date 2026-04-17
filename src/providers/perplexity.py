"""Perplexity (online) provider — OpenAI-compatible Chat Completions."""
from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from src.providers.base import LLMProvider


class PerplexityProvider(LLMProvider):
    name = "perplexity"

    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        if not api_key:
            raise ValueError("PERPLEXITY_API_KEY is required for online mode")
        self.model = model
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

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
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            tool_calls.append(
                {"id": tc.id, "name": tc.function.name, "arguments": args}
            )

        return {
            "content": msg.content,
            "tool_calls": tool_calls,
            "raw": response,
        }
