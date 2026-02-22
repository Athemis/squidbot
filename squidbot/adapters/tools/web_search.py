"""
Web search tool adapter.

Provides the agent with web search via SearXNG, DuckDuckGo, or Brave Search.
The active provider is selected from WebSearchConfig.provider at construction time.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import httpx

from squidbot.config.schema import WebSearchConfig
from squidbot.core.models import ToolDefinition, ToolResult

# ── Type alias ────────────────────────────────────────────────────────────────

_SearchResult = dict[str, str]  # keys: title, url, snippet


class WebSearchTool:
    """
    Web search tool — searches the web and returns titles, URLs, and snippets.

    Provider is determined by config.provider: "searxng", "duckduckgo", or "brave".
    All providers produce the same output format.
    """

    name = "web_search"
    description = "Search the web. Returns titles, URLs, and snippets for each result."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "max_results": {
                "type": "integer",
                "description": "Number of results to return (default: 5).",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    def __init__(self, config: WebSearchConfig) -> None:
        """
        Args:
            config: Web search configuration (provider, url, api_key).

        Raises:
            ValueError: If provider is unknown, or if Brave is selected without an api_key.
        """
        if config.provider == "searxng":
            self._backend: Callable[..., Coroutine[Any, Any, list[_SearchResult]]] = (
                lambda query, max_results: _search_searxng(
                    query, max_results, config.url, config.api_key
                )
            )
        elif config.provider == "duckduckgo":
            self._backend = _search_ddg
        elif config.provider == "brave":
            if not config.api_key:
                raise ValueError("Brave Search requires api_key to be set in config")
            self._backend = lambda query, max_results: _search_brave(
                query, max_results, config.api_key
            )
        else:
            raise ValueError(
                f"Unknown provider: {config.provider!r}. Choose: searxng, duckduckgo, brave"
            )

    def to_definition(self) -> ToolDefinition:
        """Return the tool definition for the LLM."""
        return ToolDefinition(
            name=self.name, description=self.description, parameters=self.parameters
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Run a web search and return formatted results.

        Args:
            kwargs: Must contain "query" (str) and optionally "max_results" (int, default 5).
        """
        query: str = str(kwargs.get("query", ""))
        if not query:
            return ToolResult(tool_call_id="", content="Error: query is required", is_error=True)
        try:
            max_results: int = int(kwargs.get("max_results", 5))
        except TypeError, ValueError:
            max_results = 5
        try:
            results = await self._backend(query, max_results)
        except Exception as e:
            return ToolResult(tool_call_id="", content=f"Search failed: {e}", is_error=True)

        if not results:
            return ToolResult(tool_call_id="", content=f"No results found for: {query}")

        lines: list[str] = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']} — {r['url']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet']}")
            lines.append("")
        return ToolResult(tool_call_id="", content="\n".join(lines).strip())


# ── Provider backends ─────────────────────────────────────────────────────────


async def _search_searxng(
    query: str, max_results: int, url: str, api_key: str
) -> list[_SearchResult]:
    """Search via a SearXNG instance."""
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    params = {"q": query, "format": "json", "categories": "general"}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{url.rstrip('/')}/search", params=params, headers=headers)
        response.raise_for_status()
    data = response.json()
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
        for r in data.get("results", [])[:max_results]
    ]


async def _search_ddg(query: str, max_results: int) -> list[_SearchResult]:
    """Search via DuckDuckGo (duckduckgo-search library, run in thread)."""
    from duckduckgo_search import DDGS  # noqa: PLC0415

    def _run() -> list[dict[str, str]]:
        return list(DDGS().text(query, max_results=max_results))

    raw = await asyncio.to_thread(_run)
    return [
        {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
        for r in raw
    ]


async def _search_brave(query: str, max_results: int, api_key: str) -> list[_SearchResult]:
    """Search via Brave Search API."""
    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
    }
    params = {"q": query, "count": str(max_results)}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params=params,
            headers=headers,
        )
        response.raise_for_status()
    data = response.json()
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("description", ""),
        }
        for r in data.get("web", {}).get("results", [])[:max_results]
    ]
