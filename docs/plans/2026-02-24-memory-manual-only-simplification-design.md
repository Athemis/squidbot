# Design: Memory System Simplification (Manual-Only)

**Date:** 2026-02-24  
**Status:** Proposed  
**Supersedes direction from:** `docs/plans/2026-02-23-memory-consolidation-design.md`

## Context

The current memory subsystem has grown in complexity: consolidation triggers, cursor bookkeeping,
summary persistence, meta-consolidation, and a large test surface around those behaviors.

This moved away from the original design intent in
`docs/plans/2026-02-21-squidbot-design.md`: explicit, transparent memory with no automatic
summarization.

## Problem

We need a memory system that is easy to reason about, robust in daily use, and still supports the
core use case:

- one owner
- multiple channels (CLI, Matrix, email, group chats)
- cross-channel recall
- low operational complexity

Automatic summary/cursor mechanics add moving parts and failure modes that are not strictly needed
to satisfy this use case.

## Goals

1. Radically simplify memory behavior and code paths.
2. Keep history global across channels.
3. Preserve long-term memory via `MEMORY.md`.
4. Keep historical recall available via `search_history`.
5. Reduce test and maintenance burden.

## Non-Goals

- No automatic digest/summarization in normal turn flow.
- No background or optional "digest mode" code paths.
- No token-budget engine in this change.

## Approaches Considered

### Option 1: Manual-only memory (chosen)

Context per turn:

- system prompt
- `## Your Memory` (`MEMORY.md`)
- last `N` messages from global history (labelled)
- current user message

Recall beyond `N` is explicit via `search_history`.

### Option 2: Manual-only + optional digest

Kept as a future architectural alternative only. Not implemented now and no hooks/stubs retained
in code.

### Option 3: Minimal rolling summary

Rejected because it reintroduces hidden behavior and complexity.

## Decision

Adopt **Option 1**. Remove consolidation, cursor, and summary systems entirely from active code.
Keep cross-channel global history unchanged.

Option 2 is documented as a future fallback if real-world usage shows unacceptable recall gaps,
but it must not remain in code as dormant branches.

## Detailed Design

### 1) Prompt assembly contract

`MemoryManager.build_messages()` becomes deterministic and small:

1. `load_history(last_n=history_context_messages)`
2. `load_global_memory()`
3. label history messages as today (`[channel / owner|sender]`)
4. assemble prompt blocks
5. append current user message

No consolidation trigger. No summary load. No cursor checks.

### 2) Persistence contract simplification

`MemoryPort` retains only:

- `load_history(last_n: int | None = None)`
- `append_message(message)`
- `load_global_memory()`
- `save_global_memory(content)`
- cron methods

Remove:

- `load_global_summary()` / `save_global_summary()`
- `load_global_cursor()` / `save_global_cursor()`

### 3) Configuration simplification

Replace consolidation knobs with one explicit context window setting:

- `agents.history_context_messages: int = 80`

Validation: must be `> 0`.

Remove active use of:

- `agents.consolidation_threshold`
- `agents.keep_recent_ratio`

### 4) Storage behavior

- Keep `history.jsonl` as the global append-only conversation record.
- Keep `workspace/MEMORY.md` as global long-term memory.
- Stop reading/writing `memory/summary.md` and `history.meta.json`.
- Legacy files may remain on disk and are ignored.

### 5) Recall behavior and agent guidance

- Durable facts: via `memory_write` to `MEMORY.md`.
- Older details: via `search_history` on demand.
- Update memory skill text to explicitly say: when uncertain about older details, use
  `search_history` before answering confidently.

## Error Handling

- Missing `MEMORY.md` returns empty string (current behavior).
- `search_history` failures stay tool-error results (no exceptions to user flow).
- No consolidation-related runtime failures remain because those code paths are removed.

## Testing Strategy

Focus tests on visible behavior:

1. `MemoryManager` prompt assembly with memory + last `N` labelled history.
2. `persist_exchange()` correctness.
3. Config validation for `history_context_messages`.
4. `JsonlMemory` behavior for history + global memory only.
5. `search_history` as recall path across channels.

Delete consolidation/cursor/meta-consolidation tests instead of rewriting them.

## Migration and Compatibility

- No data migration required.
- Existing history remains intact.
- Existing `MEMORY.md` remains intact.
- Obsolete summary/cursor files are ignored.

## Risks and Mitigations

- Risk: important details not in recent `N` messages and not in `MEMORY.md`.
  - Mitigation: stronger skill guidance + `search_history` usage pattern.
- Risk: initial behavior shift for users expecting automatic summary context.
  - Mitigation: document new model clearly in README/AGENTS.

## Expected Outcome

This change trades hidden automation for explicit retrieval. It better matches the original
architecture goals (simple, debuggable, robust), while preserving the core cross-channel memory
use case.
