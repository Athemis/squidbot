# Performance Optimization Design

## Goal

Eliminate 14 identified bottlenecks in squidbot. Focus areas: per-request latency
(in-memory history cache, parallel I/O), correctness fixes (blocking I/O in event loop),
resource efficiency (caching long-lived objects, parallelization).

## Architecture

Hexagonal architecture remains fully intact. `core/` receives only changes that
inherently belong there (parallelization logic in MemoryManager/AgentLoop, cache
in MemoryManager). All adapter-internal optimizations (JsonlMemory, OpenAIAdapter,
EmailChannel, RichCliChannel) stay in `adapters/`. No MemoryPort protocol changes.

## Components & Changes

### P0 Bug — heartbeat.py
`_read_heartbeat_file` reads synchronously (`path.read_text()`) directly in the async
event loop. Fix: change method to `async def`, offload I/O via `asyncio.to_thread`.

### core/memory.py — Parallel I/O + Skills-XML-Cache
`build_messages` fires `load_history` and `load_global_memory` sequentially even though
there is no data dependency. Fix: `asyncio.gather`. Skills-XML is rebuilt on every call;
cache via frozenset fingerprint of `(name, location, available, always)` tuples from the
skill list. The `always` field must be included because its value directly determines which
skill bodies are embedded in the cache value — omitting it causes stale cache hits when a
skill's frontmatter changes.

### adapters/persistence/jsonl.py — In-Memory Ring Buffer + Init-Cleanup
`mkdir` is called on every I/O call; once in `__init__` is sufficient. Largest single
gain: in-memory cache of the last N history entries as `list[Message]`.
`load_history(last_n=N)` returns cache slice when cache is large enough.
`append_message` updates cache after successful disk write. Additionally:
`append_messages(list[Message])` as optional method (not in MemoryPort protocol)
for batch writes; `MemoryManager.persist_exchange` uses it when available.

### core/agent.py — Parallel Tool Execution + Metadata-Fix
Tool calls from a single LLM turn are processed sequentially; OpenAI explicitly enables
parallel tool use. Fix: `asyncio.gather` in `_append_tool_results`.
`dict(outbound_metadata or {})` is copied per streaming chunk even though `metadata`
is never mutated. Fix: direct reference.

### adapters/llm/pool.py — Shared AsyncOpenAI Client
Each `OpenAIAdapter` instance in the pool creates its own `httpx.AsyncClient`, even when
multiple pool members have the same `api_base`. Fix: pool-level dict keyed on
`(api_base, api_key)` tuple that reuses client instances. Both fields are required as the
cache key: two pool members at the same base URL but with different credentials (e.g.,
personal and work accounts) must receive distinct clients, or the wrong API key would be
used silently.

### adapters/channels/cli.py — Console-Cache
`RichCliChannel.send` creates a new `Console()` on every call. Fix: create once in
`__init__`, store in `self._console`.

### adapters/channels/email.py — SSL-Context-Cache
`ssl.create_default_context()` (loads CA bundle from disk) is recreated on every SMTP
send and IMAP reconnect. Fix: `self._ssl_ctx` in `__init__`.

### cli/gateway.py — MCP-Parallel-Startup + MemoryWriteTool-Singleton
MCP servers are connected sequentially; `asyncio.gather` parallelizes this.
`MemoryWriteTool` is stateless but still instantiated per message; create as singleton
before the message loop. `list(owner_aliases or [])` unnecessarily copies the immutable
alias list on every message.

### adapters/tools/search_history.py — Substring-Pre-Filter
Lines are deserialized before checking if the query string appears. Fix:
`if normalized_query not in line.lower(): continue` before JSON parsing.

**Unicode caveat:** `json.dumps` encodes non-ASCII characters as `\uXXXX` escape
sequences by default. A pre-filter check against the raw JSON line would miss matches
for non-ASCII queries (e.g., `"über"` does not appear verbatim in a line containing
`"\\u00fcber"`). To avoid false negatives, `_serialize_message` must use
`ensure_ascii=False` so that content is stored as raw Unicode. This is applied together
with the pre-filter in Task 12.

### adapters/tools/files.py — Combine exists+read_text
`ReadFileTool` uses two `asyncio.to_thread` calls for one file (`exists`, then
`read_text`). Fix: single `to_thread` call with `FileNotFoundError` handling.

**Note on `_history_file` contract:** After Task 3 removes `mkdir` from `_history_file`,
the invariant that the history directory exists is provided by `JsonlMemory.__init__`.
`SearchHistoryTool` imports `_history_file` directly and relies on this ordering. In
production, `JsonlMemory` is always constructed first. Tests for `SearchHistoryTool` that
use `tmp_path` are safe because `tmp_path` already exists. Future tests that construct
a new base directory without `JsonlMemory` should call `base_dir.mkdir()` explicitly.

## Error Handling

- Ring buffer: write-first, then cache update. Cache miss triggers normal disk read.
- `asyncio.gather` in `build_messages`: exception propagates, AgentLoop handler catches
  it as before (fallback to minimal context).
- Parallel tool execution: `asyncio.gather(..., return_exceptions=True)` is used so that
  a failing tool does not cancel sibling tasks. Without `return_exceptions=True`, a
  cancelled `asyncio.to_thread` task leaves its thread running while the coroutine
  receives `CancelledError`, which can leave files partially written or other side effects
  incomplete. With `return_exceptions=True`, exceptions are caught and converted to
  `ToolResult(is_error=True)` objects, consistent with the project's error-as-value
  convention. All tool calls in a turn always complete before the next LLM round begins.

## Test Strategy

TDD: each change gets a test that directly observes the new behavior.
Existing tests remain unchanged and green. Core tests in `tests/core/`, adapter tests
in `tests/adapters/`. No shared fixtures; test doubles in respective test files.
