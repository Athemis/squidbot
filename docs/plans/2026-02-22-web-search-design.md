# Web Search Tool — Design

**Date:** 2026-02-22
**Status:** Approved

## Goal

Add a `web_search` tool that lets the agent search the web and receive titles, URLs, and
snippets. Supports three providers (SearXNG, DuckDuckGo, Brave) selected by configuration.

## Architecture

`WebSearchTool` is a single adapter class in `squidbot/adapters/tools/web_search.py`. It
implements `ToolPort` structurally (no inheritance — consistent with all other tool adapters).
The active provider is selected in the constructor based on `settings.tools.web_search.provider`.
Three private async functions (`_search_searxng`, `_search_ddg`, `_search_brave`) handle
provider-specific HTTP logic; they share no base class — only the same call signature.

Dependency direction unchanged: `adapters → ports ← core`. The tool is registered in
`cli/main.py::_make_agent_loop()` when `settings.tools.web_search.enabled`.

## Tool Interface (what the agent sees)

```
name:         web_search
description:  Search the web. Returns titles, URLs, and snippets for each result.
parameters:
  query       string   required   The search query.
  max_results integer  optional   Number of results to return (default: 5).
```

Return format (plain text, numbered):

```
1. Page Title — https://example.com/page
   A short snippet describing the page content.

2. Another Result — https://other.com
   Snippet text here.
```

Errors and empty results are returned as `ToolResult(is_error=True, ...)` — never raised.

## Providers

### SearXNG
- HTTP GET `{config.url}/search?q={query}&format=json&categories=general`
- `Authorization: Bearer {config.api_key}` header if `api_key` is set
- Uses `httpx.AsyncClient` with a 10s timeout
- Parses `results[].title`, `results[].url`, `results[].content`

### DuckDuckGo
- Uses the `duckduckgo-search` library (`DDGS().text(query, max_results=n)`)
- Run in thread executor (`asyncio.to_thread`) — the library is synchronous
- No API key required
- Returns `title`, `href`, `body` fields

### Brave Search
- HTTP GET `https://api.search.brave.com/res/v1/web/search?q={query}&count={n}`
- Header: `X-Subscription-Token: {config.api_key}`
- Uses `httpx.AsyncClient` with a 10s timeout
- Parses `web.results[].title`, `web.results[].url`, `web.results[].description`

## Config (already in schema.py)

```json
"web_search": {
  "enabled": false,
  "provider": "searxng",
  "url": "https://searxng.example.com",
  "api_key": null
}
```

`url` is only used by SearXNG. `api_key` is required for Brave, optional for SearXNG,
unused for DDG. Unknown provider value → `ValueError` at construction time (fail fast).

## Error Handling

| Situation | Behaviour |
|---|---|
| HTTP error / timeout | `ToolResult(is_error=True, content="Search failed: <status>")` |
| Empty results | `ToolResult(content="No results found for: <query>")` |
| Unknown provider | `ValueError` in `__init__` (config validation, not runtime) |
| Missing API key (Brave) | `ValueError` in `__init__` |

## New Dependency

`duckduckgo-search>=6.0` added to `[project.dependencies]` in `pyproject.toml`.

## Testing

- `tests/adapters/tools/test_web_search.py`
- SearXNG and Brave: mock `httpx.AsyncClient.get` to return fixture JSON
- DDG: mock `asyncio.to_thread` to return fixture list of dicts
- Tests cover: normal results, empty results, HTTP error, unknown provider at construction

## What Does Not Change

- `core/` — no changes
- `core/ports.py` — `ToolPort` protocol unchanged
- Other adapters — unaffected
- Existing tests — no regressions
