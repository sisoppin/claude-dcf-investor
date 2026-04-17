"""Abstract base class for LLM providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Common interface for online (Perplexity) and offline (Ollama) backends.

    Both backends expose an OpenAI-compatible Chat Completions endpoint, so we
    standardize on that message/tool schema across the codebase.
    """

    name: str = "base"

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """Send a chat completion request.

        Returns a normalized response of the form::

            {
              "content": str | None,           # assistant text
              "tool_calls": [                  # may be empty
                {
                  "id": str,
                  "name": str,
                  "arguments": dict,
                },
                ...
              ],
              "raw": <provider-specific raw response>,
            }
        """
