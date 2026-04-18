"""Local MCP server: internet search with predefined search modes.

Tools:
  - web_search(query, num_results)   : general web search
  - news_search(query, num_results)  : news-focused search
  - research(topic, num_results)     : multi-angle search synthesis
  - fetch_url(url, max_chars)        : fetch a URL and return cleaned text
"""
from __future__ import annotations

import os
import re
import time

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("search")

SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "duckduckgo").strip().lower()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
DEFAULT_MAX = int(os.getenv("SEARCH_MAX_RESULTS", "5"))

_DDG_RETRIES = 3
_DDG_BACKOFF = 2.0  # seconds between retries


# ---------- backends -------------------------------------------------------


def _ddg(query: str, num_results: int, kind: str = "text") -> list[dict]:
    """DuckDuckGo via the duckduckgo-search package, with retry on rate limit."""
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException, RatelimitException

    last_error: Exception | None = None
    for attempt in range(_DDG_RETRIES):
        if attempt > 0:
            time.sleep(_DDG_BACKOFF * attempt)
        try:
            ddgs = DDGS()
            if kind == "news":
                results = [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("body", ""),
                        "source": r.get("source", ""),
                        "date": r.get("date", ""),
                    }
                    for r in ddgs.news(query, max_results=num_results)
                ]
            else:
                results = [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    }
                    for r in ddgs.text(query, max_results=num_results)
                ]
            return results
        except RatelimitException as e:
            last_error = e
        except DDGSException as e:
            last_error = e
            break
        except Exception as e:  # noqa: BLE001
            last_error = e
            break

    raise RuntimeError(
        f"DuckDuckGo search failed after {_DDG_RETRIES} attempts: {last_error}"
    )


def _tavily(query: str, num_results: int, kind: str = "text") -> list[dict]:
    if not TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY not configured")
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "max_results": num_results,
        "topic": "news" if kind == "news" else "general",
    }
    r = httpx.post("https://api.tavily.com/search", json=payload, timeout=30)
    r.raise_for_status()
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
        }
        for item in r.json().get("results", [])
    ]


def _search(query: str, num_results: int, kind: str = "text") -> list[dict]:
    if SEARCH_PROVIDER == "tavily":
        return _tavily(query, num_results, kind)
    return _ddg(query, num_results, kind)


def _format(results: list[dict]) -> str:
    if not results:
        return "(no results)"
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r.get('title', '')}")
        if r.get("url"):
            lines.append(f"    URL: {r['url']}")
        if r.get("source") or r.get("date"):
            meta = " · ".join(filter(None, [r.get("source"), r.get("date")]))
            lines.append(f"    {meta}")
        if r.get("snippet"):
            lines.append(f"    {r['snippet']}")
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------- tools ----------------------------------------------------------


@mcp.tool()
def web_search(query: str, num_results: int = DEFAULT_MAX) -> str:
    """Run a general web search and return the top results with snippets."""
    try:
        results = _search(query, num_results, kind="text")
        return _format(results)
    except Exception as e:  # noqa: BLE001
        return f"ERROR: web_search failed — {e}"


@mcp.tool()
def news_search(query: str, num_results: int = DEFAULT_MAX) -> str:
    """Run a news-focused web search and return recent articles with snippets."""
    try:
        results = _search(query, num_results, kind="news")
        return _format(results)
    except Exception as e:  # noqa: BLE001
        return f"ERROR: news_search failed — {e}"


@mcp.tool()
def research(topic: str, num_results: int = DEFAULT_MAX) -> str:
    """Multi-angle research on a topic.

    Runs three queries (overview / latest developments / criticism) and
    returns a combined, sectioned result for the LLM to synthesize.
    """
    angles = [
        ("Overview", f"{topic} overview explained"),
        ("Latest developments", f"{topic} latest 2026"),
        ("Criticism / counterpoints", f"{topic} criticism limitations problems"),
    ]
    sections: list[str] = []
    for label, q in angles:
        try:
            results = _search(q, num_results, kind="text")
            sections.append(f"=== {label} (query: {q!r}) ===\n{_format(results)}")
        except Exception as e:  # noqa: BLE001
            sections.append(f"=== {label} (query: {q!r}) ===\nERROR: {e}")
    return "\n\n".join(sections)


@mcp.tool()
def fetch_url(url: str, max_chars: int = 8000) -> str:
    """Fetch a URL and return its cleaned text content (truncated)."""
    try:
        r = httpx.get(
            url,
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (AI-Agent)"},
        )
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        return f"ERROR fetching {url}: {e}"

    text = r.text
    # Strip script/style blocks then HTML tags
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) > max_chars:
        text = text[:max_chars] + " …[truncated]"
    return text


if __name__ == "__main__":
    mcp.run(transport="stdio")
