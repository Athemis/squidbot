# Design: Context Budget and Redundancy Control

**Date:** 2026-02-24  
**Status:** Proposed  
**Related issue:** https://github.com/Athemis/squidbot/issues/2

## Problem

Per-turn context is currently assembled from multiple sources:

- base system prompt
- `MEMORY.md` (long-term facts)
- global conversation summary
- recent labelled history

This is robust, but it can accumulate overlapping content. In practice, the same fact may appear in both Memory and Summary, and near-duplicate details may appear again in recent History. This increases token usage and can reduce signal-to-noise as history grows.

## Goals

1. Keep context compact and predictable per turn.
2. Reduce obvious redundancy between Memory and Summary.
3. Preserve recency and continuity for active conversations.
4. Avoid schema/storage migrations.

## Non-Goals

- Full token-accurate budgeting in this iteration.
- Semantic deduplication using embeddings/vector stores.
- Changes to persistence format (`history.jsonl`, `summary.md`, `MEMORY.md`).

## Approaches Considered

### A) Token-based budgeting now

Use model-specific token counting and strict per-block token limits.

**Pros:** Cost predictability, model-aligned limits.  
**Cons:** More implementation complexity and tokenizer coupling.  
**Decision:** Defer (already tracked by issue #2).

### B) Word-budget + deterministic de-duplication (recommended)

Apply fixed per-block word budgets and remove exact duplicate summary lines already present in Memory.

**Pros:** Simple, deterministic, low-risk, no new dependencies.  
**Cons:** Word count is only an approximation of token usage.

### C) Retrieval-first architecture

Retrieve relevant chunks from history/memory dynamically instead of assembling fixed blocks.

**Pros:** Potentially best relevance/efficiency long-term.  
**Cons:** Significant complexity and behavior changes; overkill for current scope.

## Decision

Implement **Approach B** as an immediate mitigation. Keep code paths simple and configurable. Revisit token-accurate budgeting in a follow-up under issue #2.

## Detailed Design

### 1) New configuration in `AgentConfig`

Add four fields under `agents`:

- `context_memory_max_words` (default: `300`)
- `context_summary_max_words` (default: `500`)
- `context_history_max_words` (default: `2500`)
- `context_dedupe_summary_against_memory` (default: `true`)

Validation: all `*_max_words` values must be `> 0`.

### 2) Prompt assembly pipeline in `MemoryManager.build_messages()`

Order of operations:

1. Load raw `global_memory`, `global_summary`, and history.
2. If enabled, de-duplicate summary lines that exactly match normalized Memory lines.
3. Truncate Memory and Summary to their configured word budgets.
4. Label history messages as before.
5. Apply history word budget using a recent-first strategy.
6. Build final system prompt sections and append user message.

### 3) De-duplication rule

Use a deterministic and conservative rule:

- Normalize by trimming whitespace and lowercasing each non-empty line.
- Remove summary lines whose normalized form already exists in Memory.
- Keep everything else untouched.

This avoids aggressive semantic matching and minimizes accidental data loss.

### 4) History budget rule

Use recent-first inclusion:

- walk history from newest to oldest
- accumulate message word cost
- stop when adding another old message would exceed budget
- reverse back to chronological order

This preserves the newest conversational detail under constrained budget.

## Error Handling and Safety

- If de-duplication results in empty Summary, omit `## Conversation Summary` block.
- If truncation is required, truncate deterministically by words.
- No persistence writes are introduced in this feature; all changes are read-time context assembly only.

## Testing Strategy

Add/extend tests to cover:

1. config defaults and validation for new fields
2. summary de-duplication against memory
3. memory and summary budget truncation
4. history budget keeps recent messages first
5. no regressions in consolidation behavior and existing memory tests

Full verification remains:

- `uv run ruff check .`
- `uv run mypy squidbot/`
- `uv run pytest`

## Rollout and Compatibility

- Backward-compatible defaults; existing configs continue to load.
- No migration required.
- Feature is tunable by config and can be relaxed/tightened without code changes.

## Follow-up

- Implement token-aware budgeting as a separate iteration (issue #2).
