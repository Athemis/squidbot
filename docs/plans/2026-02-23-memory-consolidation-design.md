# Memory Consolidation Design

**Date:** 2026-02-23
**Status:** Approved — implementation in progress

## Problem

squidbot's `MemoryManager` currently hard-prunes old messages when history exceeds `max_history_messages`. Information in pruned messages is permanently lost from the agent's context. For a daily-driver personal assistant, this means the bot "forgets" conversations after enough exchanges, even within the same session.

## Goal

Automatically summarize old conversation history into `memory.md` before it leaves context, so the agent retains the semantic content of old exchanges without carrying the full verbatim text.

## Non-Goals

- Vector embeddings / semantic search (separate feature)
- Modifying or truncating JSONL files on disk (JSONL is the source of truth — immutable)
- Cross-session consolidation (each session's memory.md is independent)

## Key Decisions

### JSONL stays immutable

Consolidation solves a *context window* problem, not a *storage* problem. The JSONL is the complete historical record and must never be modified. Only what goes into the LLM context window is affected.

### Sliding window pattern

After consolidation, context looks like:
```
[system prompt + memory.md (with summary appended)]
+ [last keep_recent messages verbatim]
+ [user message]
```

The `keep_recent` window preserves immediate conversational coherence (pronoun references, tool-call continuity). Everything older is summarized.

### Lazy trigger

Consolidation runs inside `build_messages()` — on demand, not on a timer. This keeps the architecture simple: no background tasks, no locks needed.

### Optional LLM injection

`MemoryManager` accepts `llm: LLMPort | None`. If `None`, consolidation is disabled and the existing hard-prune fallback applies. This keeps existing tests working without an LLM double.

### Append, never overwrite

Summary text is appended to the existing `memory.md` content, separated by a blank line. The agent's manually written memory (via `memory_write` tool) is preserved.

## Architecture

```
build_messages()
    │
    ├── load history from JSONL
    │
    ├── if len(history) > consolidation_threshold AND llm is set:
    │       _consolidate(session_id, history)
    │           ├── to_summarize = history[:-keep_recent]
    │           ├── recent = history[-keep_recent:]
    │           ├── call LLM with consolidation prompt + conversation text
    │           ├── append summary to memory.md
    │           └── return recent
    │
    ├── reload memory.md (may have been updated)
    ├── build system prompt (+ memory.md + skills)
    └── return [system, *recent_history, user]
```

## Configuration

| Field | Default | Meaning |
|---|---|---|
| `consolidation_threshold` | 100 | Messages above this count trigger consolidation |
| `keep_recent` | 20 | Messages always kept verbatim after consolidation |
| `consolidation_pool` | `""` | LLM pool for summarization (defaults to `llm.default_pool`) |

## Trade-offs Considered

| Option | Decision |
|---|---|
| Summarize on every call vs. only when over threshold | Only when over threshold — avoids unnecessary LLM calls |
| Overwrite memory.md vs. append | Append — preserves agent-written facts |
| Modify JSONL vs. keep immutable | Immutable — JSONL is source of truth |
| Background task vs. lazy trigger | Lazy — simpler, no async complexity |

## Files Changed

- `squidbot/config/schema.py` — 3 new fields on `AgentConfig`
- `squidbot/core/memory.py` — `_consolidate()` method + new `__init__` params
- `squidbot/cli/main.py` — wire LLM + config into `MemoryManager`
- `README.md` — document new config fields
