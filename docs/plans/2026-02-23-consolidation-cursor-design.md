# Consolidation Cursor + MemoryWriteTool Design

**Date:** 2026-02-23
**Status:** Approved

## Problem

Two related issues make the memory system unreliable:

### 1. Repeated consolidation

`_consolidate()` runs inside `build_messages()` and summarizes `history[:-keep_recent]`
into `memory.md`. But the JSONL file is immutable — messages are never removed. On every
subsequent turn (and after every process restart), `load_history()` returns the full JSONL,
`len(history) > consolidation_threshold` is still true, and `_consolidate()` fires again,
appending a new — largely redundant — summary entry to `memory.md`. In a long-lived session,
`memory.md` accumulates dozens of overlapping summaries.

### 2. `MemoryWriteTool` never registered

`MemoryWriteTool` exists in `adapters/tools/memory_write.py` and is explicitly referenced
in `_CONSOLIDATION_WARNING`: *"Use the memory_write tool now to preserve anything critical
before it happens."* But the tool is never registered in `_make_agent_loop()`, because it
requires a `session_id` at construction time — and the tool registry is built at startup
before any session exists. The warning instructs the agent to use a tool it cannot call.

## Decision

1. **Consolidation cursor** — persist a `last_consolidated` integer (message count) per
   session in a separate `.meta.json` file. `_consolidate()` only summarizes messages after
   the cursor; after summarizing, the cursor advances. Survives process restarts.

2. **`extra_tools` in `AgentLoop.run()`** — add an `extra_tools: list[ToolPort] | None`
   parameter. Tools in `extra_tools` are merged with the registry for the duration of one
   `run()` call only — no registry mutation, no race conditions in the gateway. `MemoryWriteTool`
   is instantiated with the correct `session_id` per call and passed as `extra_tools`.

## Cursor Design

### Storage

New file per session:
```
~/.squidbot/sessions/<safe-session-id>.meta.json
```
Content: `{"last_consolidated": 80}`

- Missing file → cursor = 0 (safe default: re-consolidation at worst, no data loss)
- Written atomically after a successful consolidation LLM call and `memory.md` save

### `MemoryPort` — two new methods

```python
async def load_consolidated_cursor(self, session_id: str) -> int: ...
async def save_consolidated_cursor(self, session_id: str, cursor: int) -> None: ...
```

`JsonlMemory` implements these using `sessions/<safe_id>.meta.json`.

### Consolidation trigger

Old: `len(history) > consolidation_threshold`
New: `len(history) - cursor > consolidation_threshold`

Only unconsolidated messages count toward the threshold. After a restart with 200 messages
in JSONL and cursor=180: `200 - 180 = 20`, which does not exceed threshold=100 — no
re-consolidation.

### `_consolidate()` — new algorithm

```python
cursor = await self._storage.load_consolidated_cursor(session_id)
to_summarize = history[cursor : -self._keep_recent]
recent = history[-self._keep_recent:]

if not to_summarize:
    return recent  # already consolidated, no LLM call

# summarize to_summarize via LLM
# append summary to memory.md
new_cursor = len(history) - self._keep_recent
await self._storage.save_consolidated_cursor(session_id, new_cursor)
return recent
```

### Warning trigger

Old: `len(history) >= consolidation_threshold - 2`
New: `len(history) - cursor >= consolidation_threshold - 2`

Warning fires only when unconsolidated messages are approaching the threshold — not on
every turn after the JSONL passes threshold.

## `extra_tools` Design

### `AgentLoop.run()` signature change

```python
async def run(
    self,
    session: Session,
    user_message: str,
    channel: ChannelPort,
    *,
    llm: LLMPort | None = None,
    extra_tools: list[ToolPort] | None = None,
) -> None:
```

### Tool definitions

Extra tools are merged with the registry for this call only:

```python
extra = {t.name: t for t in (extra_tools or [])}
tool_definitions = self._registry.get_definitions() + [
    ToolDefinition(name=t.name, description=t.description, parameters=t.parameters)
    for t in extra.values()
]
```

### Tool dispatch

When executing a tool call, `extra_tools` is checked first, then the registry:

```python
tool = extra.get(tc.name)
if tool is not None:
    result = await tool.execute(**tc.arguments)
    result.tool_call_id = tc.id
else:
    result = await self._registry.execute(tc.name, tool_call_id=tc.id, **tc.arguments)
```

### `MemoryWriteTool` registration in `cli/main.py`

At every `AgentLoop.run()` call site, pass:

```python
extra_tools=[MemoryWriteTool(storage=storage, session_id=session.id)]
```

This covers: CLI interactive session, gateway sessions (Matrix, Email), heartbeat, cron.

## What This Solves

| Issue | Status |
|---|---|
| Repeated consolidation / memory.md grows unboundedly | ✅ Cursor prevents re-summarizing |
| `MemoryWriteTool` never registered | ✅ Injected per-call via `extra_tools` |
| Race condition in gateway (shared registry) | ✅ No registry mutation |

## What This Does Not Solve (Features B + C)

- `search_history` does not search `memory.md` (→ superseded by global memory redesign)
- `memory_write` overwrites consolidation summary in same turn (→ Feature C)
- 2-5 sentence summary too small for large histories (→ Feature C)
- Consolidation LLM call has no system prompt (→ Feature C)
- `save_memory_doc` failure after LLM call uncaught (→ Feature C)

## Files Changed

- `squidbot/core/ports.py` — 2 new methods on `MemoryPort`
- `squidbot/adapters/persistence/jsonl.py` — implement new methods, `.meta.json` file
- `squidbot/core/memory.py` — new cursor logic in `_consolidate()`, updated triggers
- `squidbot/core/agent.py` — `extra_tools` parameter in `run()`
- `squidbot/cli/main.py` — pass `MemoryWriteTool` as `extra_tools` at all `run()` call sites
- `tests/core/test_memory.py` — update consolidation tests for cursor
- `tests/core/test_agent.py` — update for `extra_tools`
- `tests/adapters/persistence/test_jsonl.py` — new cursor tests
