# Persist Tool Events in JSONL — Design

**Date:** 2026-02-23
**Status:** Approved

## Problem

Tool-call and tool-result messages are never written to the JSONL history. After a restart,
the agent has no record of which tools it called or what they returned — even via
`search_history`. This is a gap in the "searchable long-term memory" use case: the agent
cannot recall "I ran `git status` last week and saw X".

## Decision

Extend `Message.role` with two new literal values — `"tool_call"` and `"tool_result"` —
and write one of each to the JSONL after every tool execution in the agent loop. These
messages are filtered out before the LLM context is built (the API does not know these
roles) and before consolidation (only `user`/`assistant` turns are summarised). They are
searchable via `search_history`.

## What Changes

### `squidbot/core/models.py`

`Message.role` extended:

```python
role: Literal["system", "user", "assistant", "tool", "tool_call", "tool_result"]
```

`to_openai_dict()` is unchanged — these roles are never sent to the API.

### `squidbot/core/agent.py`

New constant:

```python
_TOOL_RESULT_MAX_CHARS = 2000
```

After each tool execution (after appending the `role="tool"` message to the in-memory
`messages` list), append two messages to the JSONL via `self._memory`:

```python
# Format: "tool_name(key=value, ...)" — compact, human-readable
call_text = f"{tc.name}({', '.join(f'{k}={v!r}' for k, v in tc.arguments.items())})"
result_text = result.content
if len(result_text) > _TOOL_RESULT_MAX_CHARS:
    result_text = result_text[:_TOOL_RESULT_MAX_CHARS] + "\n[truncated]"

await self._memory.append_tool_event(session_id=session.id, call_text=call_text, result_text=result_text)
```

`append_tool_event` is a new method on `MemoryManager` (not on `MemoryPort` — it is a
convenience wrapper that calls `storage.append_message` twice):

```python
async def append_tool_event(self, session_id: str, call_text: str, result_text: str) -> None:
    await self._storage.append_message(session_id, Message(role="tool_call", content=call_text))
    await self._storage.append_message(session_id, Message(role="tool_result", content=result_text))
```

### `squidbot/core/memory.py`

**`build_messages`:** filter new roles out of history before building LLM context:

```python
history = [m for m in history if m.role not in ("tool_call", "tool_result")]
```

Applied after `load_history`, before the consolidation threshold check. This keeps
`keep_recent` and cursor arithmetic based on user/assistant turns only — consistent with
how consolidation already filters to `role in ("user", "assistant")`.

**`_consolidate`:** no change needed — already filters `role in ("user", "assistant")`.

### `squidbot/adapters/tools/search_history.py`

Include new roles in search and output:

```python
# search
if msg.role in ("user", "assistant", "tool_call", "tool_result") and query in msg.content.lower():

# output label
role_labels = {"user": "USER", "assistant": "ASSISTANT", "tool_call": "TOOL CALL", "tool_result": "TOOL RESULT"}
role_label = role_labels.get(ctx.role, ctx.role.upper())
```

## What Does NOT Change

- `MemoryPort` — `append_message` is sufficient, no new port method needed
- `JsonlMemory` — `_serialize_message` / `deserialize_message` handle any role string
- `persist_exchange` — still writes only `user` + `assistant` at end of turn
- Consolidation logic — already role-filtered, no change needed
- `.meta.json` cursor — counts only unconsolidated messages; since `build_messages`
  filters tool events before the threshold check, they don't inflate the cursor arithmetic.
  **One subtlety:** after filtering, `len(history)` used for threshold/warning checks must
  be the filtered count, not the raw count. The filter must happen before those checks.

## Trade-offs

| Question | Decision |
|---|---|
| Store full output vs. truncate | Truncate at 2000 chars with `[truncated]` marker — prevents JSONL bloat from large file reads |
| New `MemoryPort` method vs. `MemoryManager` helper | `MemoryManager` helper — avoids widening the port for a convenience function |
| Filter in `load_history` vs. `build_messages` | Filter in `build_messages` — `load_history` stays generic, `search_history` can still read all roles |
| Include `tool_call`/`tool_result` in `keep_recent` window | No — filter before threshold arithmetic so verbatim window contains only conversational turns |

## Cursor Arithmetic Note

Current flow in `build_messages`:

```
history = load_history()          # all roles
cursor = load_cursor()
if len(history) - cursor > threshold: consolidate
if len(history) - cursor >= threshold - 2: warn
```

After this change:

```
history = load_history()          # all roles
history = [m for m in history if m.role not in ("tool_call", "tool_result")]
cursor = load_cursor()
if len(history) - cursor > threshold: consolidate
if len(history) - cursor >= threshold - 2: warn
```

The cursor is stored as a message-count index. Since tool events were never in the JSONL
before, existing cursors remain valid. New sessions will have tool events interleaved but
they are filtered before cursor arithmetic — so the cursor continues to count only
`user`/`assistant`/`tool` messages, consistent with what consolidation processes.

**Edge case:** The cursor points into the raw JSONL index, not the filtered index. After
filtering, `history[cursor:-keep_recent]` in `_consolidate` would be wrong if tool events
appear before the cursor position. Fix: `_consolidate` must also filter before slicing, or
the cursor must be stored as a filtered-history index.

**Decision:** Store cursor as filtered-history index. Filter in `build_messages` before
passing to `_consolidate`. `_consolidate` receives already-filtered history and cursor
remains correct.

## Files Changed

| File | Change |
|---|---|
| `squidbot/core/models.py` | Extend `Message.role` Literal |
| `squidbot/core/agent.py` | Add `_TOOL_RESULT_MAX_CHARS`, write tool events after each tool execution |
| `squidbot/core/memory.py` | Add `append_tool_event`; filter tool events in `build_messages` before history is used |
| `squidbot/adapters/tools/search_history.py` | Include `tool_call`/`tool_result` in search and output |
| `tests/core/test_agent.py` | New tests: tool events written to storage |
| `tests/core/test_memory.py` | Update: filter verified, threshold arithmetic unaffected |
| `tests/adapters/tools/test_search_history.py` | New tests: tool events appear in search results |
