"""Centralized configuration loaded from .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value else default
    except ValueError:
        return default


def _float(value: str | None, default: float) -> float:
    try:
        return float(value) if value else default
    except ValueError:
        return default


@dataclass
class Settings:
    # Mode
    mode: str

    # Perplexity
    perplexity_api_key: str
    perplexity_model: str
    perplexity_base_url: str

    # Ollama
    ollama_base_url: str
    ollama_model: str
    ollama_api_key: str

    # Agent
    max_iterations: int
    temperature: float
    verbose: bool
    system_prompt_path: str

    # MCP
    mcp_config_path: str

    # Search
    search_provider: str
    tavily_api_key: str
    search_max_results: int

    # File editor
    workspace_path: str

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            mode=os.getenv("AGENT_MODE", "online").strip().lower(),
            perplexity_api_key=os.getenv("PERPLEXITY_API_KEY", "").strip(),
            perplexity_model=os.getenv("PERPLEXITY_MODEL", "sonar").strip(),
            perplexity_base_url=os.getenv(
                "PERPLEXITY_BASE_URL", "https://api.perplexity.ai"
            ).strip(),
            ollama_base_url=os.getenv(
                "OLLAMA_BASE_URL", "http://localhost:11434/v1"
            ).strip(),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1").strip(),
            ollama_api_key=os.getenv("OLLAMA_API_KEY", "ollama").strip(),
            max_iterations=_int(os.getenv("MAX_ITERATIONS"), 10),
            temperature=_float(os.getenv("TEMPERATURE"), 0.3),
            verbose=_bool(os.getenv("VERBOSE"), True),
            system_prompt_path=os.getenv("SYSTEM_PROMPT_PATH", "").strip(),
            mcp_config_path=os.getenv(
                "MCP_CONFIG_PATH", "./config/mcp_servers.json"
            ).strip(),
            search_provider=os.getenv("SEARCH_PROVIDER", "duckduckgo").strip().lower(),
            tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
            search_max_results=_int(os.getenv("SEARCH_MAX_RESULTS"), 5),
            workspace_path=os.getenv("WORKSPACE_PATH", "./workspace").strip(),
        )

    def workspace(self) -> Path:
        p = Path(self.workspace_path).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    def validate(self) -> list[str]:
        """Return list of error strings (empty == valid)."""
        errors: list[str] = []
        if self.mode not in {"online", "offline"}:
            errors.append(f"AGENT_MODE must be 'online' or 'offline', got '{self.mode}'")
        if self.mode == "online" and not self.perplexity_api_key:
            errors.append("AGENT_MODE=online but PERPLEXITY_API_KEY is empty")
        if self.search_provider == "tavily" and not self.tavily_api_key:
            errors.append("SEARCH_PROVIDER=tavily but TAVILY_API_KEY is empty")
        return errors


settings = Settings.load()
