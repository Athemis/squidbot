# Design: Context Budget and Redundancy Control (AGENTS-Aligned)

**Date:** 2026-02-24  
**Status:** Proposed  
**Related issues:**  
- Primary: https://github.com/Athemis/squidbot/issues/2  
- Dependency risk: https://github.com/Athemis/squidbot/issues/7

## Problem Validation

The current prompt assembly in `MemoryManager.build_messages()` appends:

- base system prompt
- `MEMORY.md` (`## Your Memory`)
- global summary (`## Conversation Summary`)
- labelled recent history

without any explicit per-block context budget or read-time de-duplication.

This creates two real problems:

1. **Unbounded prompt growth by content size:** the history window is message-count-based, not size-based.
2. **Cross-block redundancy:** facts can appear in Memory and Summary simultaneously, then reappear in recent history.

Issue #2 asks for token-budget-based cutoff. This design addresses the same operational pain immediately, but
in two phases, keeping the first phase lightweight.

## Goals

1. Keep per-turn context compact and predictable.
2. Reduce obvious redundancy between Memory and Summary deterministically.
3. Preserve recent conversational continuity across channels.
4. Stay compliant with AGENTS principles: readable, test-driven, lightweight.
5. Avoid persistence/schema migrations.

## Non-Goals

- Full token-perfect budgeting in phase 1.
- Embedding/vector retrieval.
- Changes to storage format (`history.jsonl`, `summary.md`, `MEMORY.md`).
- Mandatory tokenizer dependency for all users.

## Constraints from AGENTS.md

- `core/` remains adapter-independent (hexagonal boundary).
- TDD is required: failing tests first, then implementation.
- No heavy new dependency in phase 1; startup must stay fast.
- Verification standard before completion: `ruff`, `mypy --strict`, `pytest`.

## Decision

Adopt a **two-phase design**:

- **Phase 1 (this design/plan):** word-budget controls + deterministic de-duplication + strong invariants.
- **Phase 2 (follow-up for issue #2 closure):** optional token-budget mode with graceful fallback to words.

This gives immediate mitigation without blocking a tokenizer-backed future.

## Detailed Design

### 1) Configuration (`AgentConfig`)

Add:

- `context_budget_mode: Literal["words", "tokens"] = "words"`
- `context_memory_max_words: int = 300`
- `context_summary_max_words: int = 500`
- `context_history_max_words: int = 2500`
- `context_total_max_words: int = 4500`
- `context_dedupe_summary_against_memory: bool = True`
- `context_min_recent_messages: int = 2`

Validation:

- all word limits and `context_min_recent_messages` must be `> 0`
- `context_total_max_words >= context_history_max_words`
- mode must be one of `"words"`, `"tokens"`

Notes:

- Phase 1 executes only words mode behavior.
- Tokens mode is accepted in config now to avoid later config churn.

### 2) Prompt Assembly Pipeline (`MemoryManager.build_messages()`)

Order (deterministic):

1. Load raw memory, summary, history.
2. If enabled, de-duplicate summary lines already present in memory.
3. Apply per-block truncation to memory and summary.
4. Label history messages (existing behavior).
5. Apply recent-first history budget with minimum recent-message floor.
6. Enforce total context budget by trimming in this order:
   - history first
   - summary second
   - memory last
7. Build final system message and append user message.

### 3) De-duplication Rule

Conservative, deterministic normalization for line matching:

- trim leading/trailing whitespace
- lowercase
- strip simple bullet markers (`-`, `*`, `•`) prefix
- collapse repeated internal whitespace

If normalized summary line equals any normalized memory line, drop that summary line.
Everything else remains unchanged.

### 4) History Budget Rule

Recent-first inclusion:

- walk newest to oldest
- keep adding while within budget
- always keep at least newest `context_min_recent_messages` history messages
- return in chronological order

Invariants:

- chronology preserved
- newest history message preserved
- no role/channel/sender metadata mutation

### 5) Optional Tokenizer Mode (Phase 2)

When `context_budget_mode="tokens"`:

- use a token counter abstraction provided via composition root
- if unavailable, fall back to words mode and log one warning
- no hard runtime failure because tokenizer is missing

This keeps the default path lightweight while making issue #2 closable later.

### 6) Observability

Add debug-level budget telemetry (no persistence impact):

- words before/after per block (memory, summary, history)
- number of removed summary lines
- whether fallback from tokens->words occurred

## Error Handling and Safety

- If de-duplication empties summary, omit `## Conversation Summary`.
- Truncation is deterministic and side-effect-free (read-time only).
- No new writes to storage.

## Testing Strategy

Required coverage:

1. config defaults/validation for new fields
2. de-duplication behavior (positive and negative cases)
3. exact budget truncation of memory/summary/history
4. history ordering + minimum-recent invariant
5. total-budget enforcement order
6. token-mode fallback behavior (phase 2 scaffolding tests)
7. no regression in consolidation/cursor semantics (issue #7 interactions)

Tests must assert observable outcomes, not duplicate implementation details.

## Issue Mapping and Closure Criteria

- **This design phase mitigates issue #2 but does not close it.**
- Issue #2 is closable only when token-budget mode is implemented and verified in runtime behavior.
- If issue #7 is unresolved in target branch, complete #7 first or rebase on the fix.

## Rollout and Compatibility

- Backward-compatible defaults.
- No storage migration.
- Configurable strictness by environment/user preference.
