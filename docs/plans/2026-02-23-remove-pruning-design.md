# Remove Pruning / Pre-Consolidation Warning Design

**Date:** 2026-02-23
**Status:** Approved — supersedes earlier "remove pruning" draft (2026-02-23)

> **Change from earlier draft:** Original plan was to remove pruning entirely with no
> replacement. After discussion, the decision is to keep a warning mechanism but couple it
> to the consolidation threshold instead of the defunct prune threshold. Additionally,
> `keep_recent` is replaced by `keep_recent_ratio` (a ratio of the consolidation threshold)
> for better scaling.

## Problem

`MemoryManager` has two overlapping history-limiting mechanisms:

1. **Consolidation** — summarizes old messages into `memory.md` via LLM, keeps
   `keep_recent` messages verbatim. Fires at `consolidation_threshold` (default 100).
2. **Pruning** — hard-cuts history at `max_history_messages` (default 200), injects
   `_PRUNE_WARNING` at 80% of that (160 messages).

After consolidation runs, history is reduced to `keep_recent` (20). The prune threshold
(200) and warn threshold (160) can never be reached afterwards. Pruning is structurally
dead code when consolidation is active.

The `_PRUNE_WARNING` is also misaligned: it warns the agent to save information *before
pruning*, which is the right idea — but it fires *after* the consolidation threshold,
meaning it never fires at all.

## Decision

1. **Remove pruning** — `max_history_messages` parameter, `_max_history`, `_warn_threshold`,
   the hard-cut block, and `_PRUNE_WARNING` are all deleted.
2. **Add pre-consolidation warning** — warn the agent one turn before consolidation fires,
   so it can use `memory_write` to preserve critical information before it is summarized.
3. **Replace `keep_recent` with `keep_recent_ratio`** — a float (0–1) expressing how many
   recent messages to keep as a fraction of `consolidation_threshold`. Scales automatically
   when the threshold is tuned.

## What Gets Removed

- `max_history_messages` parameter from `MemoryManager.__init__`
- `self._max_history` instance variable
- `self._warn_threshold` instance variable
- `_PRUNE_WARNING` module-level constant
- Prune block in `build_messages()` (`near_limit` calculation, hard-cut, warning injection)
- `keep_recent: int` from `AgentConfig` in `config/schema.py`
- `max_history_messages` from `cli/main.py` `MemoryManager(...)` call

## What Changes

### `_PRUNE_WARNING` → `_CONSOLIDATION_WARNING`

```python
_CONSOLIDATION_WARNING = (
    "\n\n[System: Conversation history will soon be summarized and condensed. "
    "Use the memory_write tool now to preserve anything critical before it happens.]\n"
)
```

### Warning threshold

Warning fires when `len(history) >= consolidation_threshold - 2`. The `-2` accounts for
the two messages (user + assistant) added per turn — so the warning fires exactly one turn
before consolidation would trigger.

### `keep_recent_ratio`

`keep_recent: int = 20` in `AgentConfig` is replaced by `keep_recent_ratio: float = 0.2`.

`MemoryManager` computes `keep_recent` internally:
```python
keep_recent = int(consolidation_threshold * keep_recent_ratio)
```

Validator: `0 < keep_recent_ratio < 1`.

### `consolidation_threshold` TODO

```python
consolidation_threshold: int = 100  # TODO: replace with token-based threshold
```

## What Stays

- `consolidation_threshold` — triggers consolidation
- `_consolidate()` method — unchanged
- `consolidation_pool` — unchanged
- All consolidation tests — updated (remove `max_history_messages`, update `keep_recent`)

## Architecture: `build_messages()` after change

```
build_messages()
    │
    ├── load history from JSONL
    │
    ├── if len(history) > consolidation_threshold AND llm is set:
    │       _consolidate(session_id, history)   ← unchanged
    │       reload memory_doc
    │
    ├── build system prompt (+ memory.md + skills)
    │
    ├── if len(history) >= consolidation_threshold - 2:
    │       append _CONSOLIDATION_WARNING to system prompt
    │
    └── return [system, *history, user]
```

## Configuration

| Field | Old | New | Meaning |
|---|---|---|---|
| `max_history_messages` | `int = 200` | **removed** | Was prune limit — dead code |
| `keep_recent` | `int = 20` | **removed** | Replaced by ratio |
| `keep_recent_ratio` | — | `float = 0.2` | Fraction of threshold kept verbatim |
| `consolidation_threshold` | `int = 100` | `int = 100` (+ TODO) | Unchanged |

## Impact

- `MemoryManager.__init__` loses `max_history_messages` and `keep_recent`, gains `keep_recent_ratio`
- `AgentConfig` loses `keep_recent`, gains `keep_recent_ratio`
- `cli/main.py` removes `max_history_messages=200`, updates `keep_recent` → `keep_recent_ratio`
- Tests: prune test deleted, consolidation tests updated, 2 new warning tests added
- Net result: fewer parameters, single history-limiting mechanism, warning actually fires
