# Global Memory Redesign (Feature B)

**Date:** 2026-02-23
**Status:** Approved

## Problem

The current memory model is purely per-session: `memory.md` lives under
`~/.squidbot/memory/<session-id>/memory.md`. When the agent learns something
important — a user preference, an ongoing project, a key fact — that knowledge
is trapped in the session where it was written. A new CLI session starts with
no long-term memory at all, making squidbot feel amnesiac across restarts.

Additionally, the existing `memory.md` file is overwritten wholesale by
`memory_write`, but it is _also_ appended-to by the auto-consolidation system.
These two writers conflict: a `memory_write` call in the same turn as a
consolidation will silently discard the consolidation summary.

## Decision: Two-Level Memory Model

| Level | Path | Owner | Lifetime |
|---|---|---|---|
| Global | `~/.squidbot/workspace/MEMORY.md` | Agent (via `memory_write`) | Cross-session, permanent |
| Per-session summary | `~/.squidbot/memory/<session-id>/summary.md` | Consolidation system | Per-session, auto-generated |

### Global `MEMORY.md`

- Injected into every system prompt (all sessions, all channels).
- Written exclusively by the agent via `memory_write`.
- Full overwrite semantics — the agent is responsible for curating the content.
- Content: user preferences, ongoing projects, key facts worth remembering
  across sessions.
- The memory skill instructs the agent to keep it concise (target: ≤ 300 words).

### Per-session `summary.md`

- Written exclusively by the consolidation system (`_consolidate()`).
- Renamed from `memory.md` to `summary.md` to reflect its auto-generated nature.
- Injected into the system prompt for its own session only.
- Never touched by `memory_write`.

## Port Changes

`MemoryPort` gains two new method pairs (replacing the current pair):

```python
# Global memory (cross-session)
async def load_global_memory(self) -> str: ...
async def save_global_memory(self, content: str) -> None: ...

# Per-session consolidation summary (auto-generated)
async def load_session_summary(self, session_id: str) -> str: ...
async def save_session_summary(self, session_id: str, content: str) -> None: ...
```

The existing `load_memory_doc` / `save_memory_doc` pair is **removed** from
`MemoryPort` and `JsonlMemory` once all callers are migrated.

## Filesystem Layout

```
~/.squidbot/
├── workspace/
│   └── MEMORY.md                        ← NEW: global, agent-curated
├── sessions/
│   ├── <session-id>.jsonl               ← unchanged
│   └── <session-id>.meta.json           ← NEW: consolidation cursor (Feature A)
└── memory/
    └── <session-id>/
        └── summary.md                   ← renamed from memory.md
```

`_global_memory_file(base_dir)` → `base_dir / "workspace" / "MEMORY.md"`
`_session_summary_file(base_dir, session_id)` → `base_dir / "memory" / safe_id / "summary.md"`

Both helper functions create parent directories on first use.

## System Prompt Injection

`MemoryManager.build_messages()` is updated:

```python
global_memory = await self._storage.load_global_memory()
session_summary = await self._storage.load_session_summary(session_id)

if global_memory.strip():
    full_system += f"\n\n## Your Memory\n\n{global_memory}"
if session_summary.strip():
    full_system += f"\n\n## Conversation Summary\n\n{session_summary}"
```

Order: global memory first (permanent facts), session summary second
(recent context from this session).

## `memory_write` Tool

`MemoryWriteTool.execute()` calls `save_global_memory()` instead of
`save_memory_doc()`. The tool description is updated to reflect that it
writes to a cross-session global memory:

> "Update your long-term memory. This is a global document shared across all
> sessions — use it to persist user preferences, ongoing projects, and key facts.
> The content REPLACES the current memory document entirely."

The `session_id` constructor argument is no longer needed by `memory_write`
itself (global memory has no session ID). However, `memory_write` is still
instantiated per-call (from Feature A `extra_tools`), so we keep the signature
unchanged for now to avoid a simultaneous refactor. The `session_id` is ignored
by `memory_write` but required by the `extra_tools` wiring in `main.py`.

## Consolidation System

`_consolidate()` calls `save_session_summary()` instead of `save_memory_doc()`.
After consolidation, `build_messages()` reloads `session_summary` (not
`memory_doc`) — this also eliminates the reload-after-consolidation call for
global memory (global memory is not touched by consolidation).

## Migration

No data migration is needed for existing sessions. Old `memory.md` files are
left in place and ignored — the new code reads `summary.md` (absent = empty
string). If a user has manually curated a `memory.md`, they can copy it to
`workspace/MEMORY.md` by hand.

## What This Solves

| Issue | Status |
|---|---|
| Agent loses memory across session restarts | ✅ Global MEMORY.md injected every session |
| `memory_write` and consolidation write same file | ✅ Separated: `MEMORY.md` vs `summary.md` |
| Agent can read but not navigate past sessions | Unchanged (search_history covers JSONL) |
| `search_history` searches `MEMORY.md` | Not needed — always in context |

## Files Changed

- `squidbot/core/ports.py` — replace `load/save_memory_doc` with 4 new methods
- `squidbot/adapters/persistence/jsonl.py` — implement new methods; new path helpers
- `squidbot/core/memory.py` — use `load/save_global_memory` and `load/save_session_summary`
- `squidbot/adapters/tools/memory_write.py` — call `save_global_memory()`; update description
- `tests/core/test_memory.py` — update for new method names
- `tests/adapters/persistence/test_jsonl.py` — new tests for global/session-summary paths
- `tests/adapters/tools/test_memory_write.py` — update mock expectations
