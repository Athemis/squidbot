# Gateway memory_write Fix — Design

**Date:** 2026-02-23
**Status:** Approved

## Problem

`_channel_loop_with_state` and `_channel_loop` in `cli/main.py` call `agent_loop.run()`
without `extra_tools`, so agents running via Matrix or Email cannot call `memory_write`.
All other call-sites (CLI chat, cron, heartbeat) already pass `extra_tools` correctly.

Both Matrix and Email channels have sender filtering (`allowlist` / `allow_from`) that
prevents unauthorized senders from reaching the agent at all, so there is no security
concern with giving the agent `memory_write` access.

## Decision

Add `storage: JsonlMemory` as a parameter to both `_channel_loop_with_state` and
`_channel_loop`. Each iteration constructs `MemoryWriteTool(storage=storage)` and passes
it as `extra_tools` — exactly the same pattern used by every other call-site.

Add a `# TODO` comment on `_make_agent_loop`'s return type annotation noting that all
`storage` references in `main.py` should eventually be typed as `MemoryPort` once a
second persistence implementation exists.

## What Changes

- `_channel_loop_with_state(channel, loop, state)` → `_channel_loop_with_state(channel, loop, state, storage: JsonlMemory)`
- `_channel_loop(channel, loop)` → `_channel_loop(channel, loop, storage: JsonlMemory)`
- Two call-sites in `_run_gateway` updated to pass `storage`
- `# TODO` comment added to `_make_agent_loop` return type

## What Does Not Change

- No new ports, classes, or config fields
- `MemoryWriteTool` construction is identical to existing call-sites
- Channel filtering logic (allowlist / allow_from) is untouched

## Architecture Note

`_channel_loop_with_state` and `_channel_loop` are private CLI helpers called only from
`_run_gateway`, where `storage` is already `JsonlMemory`. Using `JsonlMemory` as the
parameter type is consistent with the rest of `main.py`.

Using `MemoryPort` (the abstract port) would be architecturally cleaner but premature:
`_make_agent_loop` returns `JsonlMemory` concretely, so callers are already coupled to
the concrete type. The TODO captures the intent to fix this holistically later.

## Testing

One new test in `tests/cli/test_channel_loops.py` (or inline in an existing test module):
- Verify `_channel_loop_with_state` calls `loop.run` with a non-empty `extra_tools` list
- Use `AsyncMock` for `loop.run`, a minimal `InMemoryStorage`-backed `MemoryWriteTool`,
  and a fake channel that yields one message
