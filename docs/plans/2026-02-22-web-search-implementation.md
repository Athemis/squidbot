# Web Search Tool Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement a `WebSearchTool` adapter that gives the agent web search via SearXNG, DuckDuckGo, or Brave Search — selected by config.

**Architecture:** Single `WebSearchTool` class in `squidbot/adapters/tools/web_search.py` implementing `ToolPort` structurally. Three private async backend functions handle provider-specific HTTP. Registered in `cli/main.py::_make_agent_loop()` when `settings.tools.web_search.enabled`. No changes to core.

**Tech Stack:** Python 3.14, httpx (already a dep), duckduckgo-search (new dep), pytest, unittest.mock.

---

### Task 1: Add `duckduckgo-search` dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add the dependency**

In `pyproject.toml`, add `"duckduckgo-search>=6.0"` to the `dependencies` list after `rich>=13.0`:

```toml
dependencies = [
    ...
    "rich>=13.0",
    "duckduckgo-search>=6.0",
]
```

**Step 2: Sync**

Run: `uv sync`
Expected: `duckduckgo-search` appears in resolved packages, no errors.

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add duckduckgo-search"
```

---

### Task 2: Write failing tests for `WebSearchTool`

**Files:**
- Create: `tests/adapters/tools/__init__.py` (empty)
- Create: `tests/adapters/tools/test_web_search.py`

**Step 1: Create `__init__.py`**

Create `tests/adapters/tools/__init__.py` — empty file.

**Step 2: Write the tests**

Create `tests/adapters/tools/test_web_search.py`:

```python
"""Tests for WebSearchTool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from squidbot.adapters.tools.web_search import WebSearchTool
from squidbot.config.schema import WebSearchConfig


def _config(provider: str = "searxng", url: str = "http://searx.local", api_key: str = "") -> WebSearchConfig:
    return WebSearchConfig(enabled=True, provider=provider, url=url, api_key=api_key)


class TestWebSearchToolInterface:
    def test_name(self):
        tool = WebSearchTool(config=_config())
        assert tool.name == "web_search"

    def test_description_mentions_search(self):
        tool = WebSearchTool(config=_config())
        assert "search" in tool.description.lower()

    def test_parameters_has_query(self):
        tool = WebSearchTool(config=_config())
        assert "query" in tool.parameters["properties"]

    def test_parameters_has_max_results(self):
        tool = WebSearchTool(config=_config())
        assert "max_results" in tool.parameters["properties"]

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            WebSearchTool(config=_config(provider="bing"))

    def test_brave_missing_api_key_raises(self):
        with pytest.raises(ValueError, match="api_key"):
            WebSearchTool(config=_config(provider="brave", api_key=""))


class TestWebSearchToolSearxng:
    @pytest.mark.asyncio
    async def test_returns_formatted_results(self):
        tool = WebSearchTool(config=_config(provider="searxng", url="http://searx.local"))
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "results": [
                {"title": "Page One", "url": "https://one.com", "content": "Snippet one."},
                {"title": "Page Two", "url": "https://two.com", "content": "Snippet two."},
            ]
        }
        with patch("squidbot.adapters.tools.web_search.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=fake_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tool.execute(query="test query", max_results=2)

        assert not result.is_error
        assert "Page One" in result.content
        assert "https://one.com" in result.content
        assert "Snippet one." in result.content

    @pytest.mark.asyncio
    async def test_empty_results(self):
        tool = WebSearchTool(config=_config(provider="searxng"))
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {"results": []}
        with patch("squidbot.adapters.tools.web_search.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=fake_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tool.execute(query="nothing", max_results=5)

        assert not result.is_error
        assert "No results" in result.content

    @pytest.mark.asyncio
    async def test_http_error_returns_error_result(self):
        tool = WebSearchTool(config=_config(provider="searxng"))
        with patch("squidbot.adapters.tools.web_search.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tool.execute(query="test", max_results=5)

        assert result.is_error
        assert "Search failed" in result.content


class TestWebSearchToolDdg:
    @pytest.mark.asyncio
    async def test_returns_formatted_results(self):
        tool = WebSearchTool(config=_config(provider="duckduckgo"))
        fake_results = [
            {"title": "DDG One", "href": "https://ddg-one.com", "body": "DDG snippet."},
        ]
        with patch(
            "squidbot.adapters.tools.web_search.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=fake_results,
        ):
            result = await tool.execute(query="ddg test", max_results=1)

        assert not result.is_error
        assert "DDG One" in result.content
        assert "https://ddg-one.com" in result.content

    @pytest.mark.asyncio
    async def test_error_returns_error_result(self):
        tool = WebSearchTool(config=_config(provider="duckduckgo"))
        with patch(
            "squidbot.adapters.tools.web_search.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=Exception("ddg error"),
        ):
            result = await tool.execute(query="test", max_results=5)

        assert result.is_error
        assert "Search failed" in result.content


class TestWebSearchToolBrave:
    @pytest.mark.asyncio
    async def test_returns_formatted_results(self):
        tool = WebSearchTool(config=_config(provider="brave", api_key="test-key"))
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "web": {
                "results": [
                    {"title": "Brave One", "url": "https://brave-one.com", "description": "Brave snippet."},
                ]
            }
        }
        with patch("squidbot.adapters.tools.web_search.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=fake_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tool.execute(query="brave test", max_results=1)

        assert not result.is_error
        assert "Brave One" in result.content
        assert "https://brave-one.com" in result.content
```

**Step 3: Run tests — confirm ImportError**

Run: `uv run pytest tests/adapters/tools/test_web_search.py -v`
Expected: `ImportError: cannot import name 'WebSearchTool'`

**Step 4: Commit**

```bash
git add tests/adapters/tools/
git commit -m "test: add failing tests for WebSearchTool"
```

---

### Task 3: Implement `WebSearchTool`

**Files:**
- Create: `squidbot/adapters/tools/web_search.py`

**Step 1: Create the file**

Create `squidbot/adapters/tools/web_search.py`:

```python
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
                lambda query, max_results: _search_searxng(query, max_results, config.url, config.api_key)
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
            raise ValueError(f"Unknown provider: {config.provider!r}. Choose: searxng, duckduckgo, brave")

    def to_definition(self) -> ToolDefinition:
        """Return the tool definition for the LLM."""
        return ToolDefinition(name=self.name, description=self.description, parameters=self.parameters)

    async def execute(self, query: str, max_results: int = 5, **_: object) -> ToolResult:
        """
        Run a web search and return formatted results.

        Args:
            query: The search query string.
            max_results: Maximum number of results to return.
        """
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


# ── Type alias ────────────────────────────────────────────────────────────────

_SearchResult = dict[str, str]  # keys: title, url, snippet


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
```

**Step 2: Run the new tests**

Run: `uv run pytest tests/adapters/tools/test_web_search.py -v`
Expected: All tests PASS.

**Step 3: Run full suite**

Run: `uv run pytest -v`
Expected: All tests PASS (no regressions).

**Step 4: Ruff**

Run: `uv run ruff check squidbot/adapters/tools/web_search.py`
Expected: No errors.

**Step 5: Commit**

```bash
git add squidbot/adapters/tools/web_search.py
git commit -m "feat: add WebSearchTool with SearXNG, DuckDuckGo, and Brave backends"
```

---

### Task 4: Register `WebSearchTool` in `_make_agent_loop()`

**Files:**
- Modify: `squidbot/cli/main.py`

**Step 1: Add registration block**

In `squidbot/cli/main.py`, inside `_make_agent_loop()`, after the existing tool registrations (after line `registry.register(ListFilesTool(...))`), add:

```python
    if settings.tools.web_search.enabled:
        from squidbot.adapters.tools.web_search import WebSearchTool  # noqa: PLC0415
        registry.register(WebSearchTool(config=settings.tools.web_search))
```

**Step 2: Ruff**

Run: `uv run ruff check squidbot/cli/main.py`
Expected: No errors.

**Step 3: Run full suite**

Run: `uv run pytest -v`
Expected: All tests PASS.

**Step 4: Commit**

```bash
git add squidbot/cli/main.py
git commit -m "feat: register WebSearchTool in agent loop when enabled"
```

---

### Task 5: Smoke-test and reinstall

**Step 1: Reinstall CLI**

Run: `uv tool install --reinstall /home/alex/git/squidbot`
Expected: Installed successfully.

**Step 2: Verify help**

Run: `squidbot --help`
Expected: No errors.

**Step 3: Final test + lint pass**

Run: `uv run pytest -v && uv run ruff check squidbot/`
Expected: All tests pass, no lint errors.
