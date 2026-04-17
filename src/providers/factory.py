"""Factory selecting Perplexity vs Ollama based on AGENT_MODE."""
from __future__ import annotations

from src.config import Settings
from src.providers.base import LLMProvider
from src.providers.ollama import OllamaProvider
from src.providers.perplexity import PerplexityProvider


def build_provider(settings: Settings) -> LLMProvider:
    if settings.mode == "online":
        return PerplexityProvider(
            api_key=settings.perplexity_api_key,
            model=settings.perplexity_model,
            base_url=settings.perplexity_base_url,
        )
    if settings.mode == "offline":
        return OllamaProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            api_key=settings.ollama_api_key,
        )
    raise ValueError(f"Unknown AGENT_MODE: {settings.mode!r}")
