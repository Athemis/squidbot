# Memory System Small Fixes (Feature C)

**Date:** 2026-02-23
**Status:** Approved

## Problem

Three small issues degrade the quality of memory consolidation:

### 1. Summary budget too small

`_CONSOLIDATION_PROMPT` asks for "2-5 sentences". For a history of 200 messages
this produces a hopelessly compressed summary that loses important context. The
budget is a hard-coded constant unrelated to the size of the input.

### 2. No system prompt for consolidation LLM call

The LLM call that generates the summary is sent without a system prompt. Without
guidance the model may add preamble ("Here is a summary:"), commentary, or
formatting noise that degrades the memory document.

### 3. `save_session_summary` failure uncaught

After a successful LLM call, `_consolidate()` calls `save_session_summary()`.
If that write fails (disk full, permission error), the exception propagates up
through `build_messages()` → `AgentLoop.run()` and surfaces as a generic error
to the user — the LLM work is wasted and the turn fails.

Note: Fix #1 from the original Feature C list ("memory_write overwrites
consolidation summary") is resolved by Feature B (separate files), so it is
not addressed here.

## Decisions

### Fix 1 — Dynamic summary budget

Replace the hard-coded "2-5 sentences" with a formula:

```python
sentence_budget = max(5, len(to_summarize) // 10)
```

| `len(to_summarize)` | budget |
|---|---|
| < 50 | 5 sentences |
| 100 | 10 sentences |
| 200 | 20 sentences |
| 500 | 50 sentences |

The `//10` ratio means roughly one sentence per 10 messages — a reasonable
density. The `max(5, …)` floor prevents pathologically short summaries for
small inputs.

The prompt becomes:

```python
_CONSOLIDATION_PROMPT = (
    "Summarize the following conversation history into a concise memory entry. "
    "Focus on key facts, decisions, and context useful for future conversations. "
    "Do not include small talk or filler.\n\n"
    "Conversation history:\n{history}\n\n"
    "Provide a summary of approximately {sentences} sentences suitable for "
    "appending to a memory document."
)
```

Called as: `_CONSOLIDATION_PROMPT.format(history=history_text, sentences=sentence_budget)`

### Fix 2 — Minimal system prompt for consolidation LLM

Add a focused system prompt passed as the first message in the consolidation
LLM call:

```python
_CONSOLIDATION_SYSTEM = (
    "You are a memory consolidation assistant. "
    "Your sole task is to produce concise, factual summaries of conversation history. "
    "Output only the summary text — no preamble, no commentary, no formatting."
)
```

The consolidation call becomes:

```python
summary_messages = [
    Message(role="system", content=_CONSOLIDATION_SYSTEM),
    Message(role="user", content=prompt),
]
```

### Fix 3 — Catch `save_session_summary` failure

Wrap the save call in a `try/except` with the same strategy as the LLM call:
log a warning and return `recent` — the turn continues normally without a crash.

```python
try:
    await self._storage.save_session_summary(session_id, updated)
    await self._storage.save_consolidated_cursor(session_id, new_cursor)
except Exception as e:
    logger.warning("Failed to save consolidation summary, skipping: {}", e)
    return recent
```

Both the summary save and cursor save are wrapped together — if either fails,
neither is persisted (consistent state: next turn will re-consolidate).

## Files Changed

- `squidbot/core/memory.py` — update `_CONSOLIDATION_PROMPT`, add
  `_CONSOLIDATION_SYSTEM`, dynamic `sentence_budget`, catch save failure
- `tests/core/test_memory.py` — update prompt assertions, add test for save failure
