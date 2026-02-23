# Meta-Consolidation of Session Summary — Design Document

**Date:** 2026-02-23
**Status:** Approved
**Replaces:** D3 in `docs/plans/2026-02-23-memory-system-cleanup-design.md`

---

## Problem Statement

`MemoryManager._consolidate()` appends each new consolidation cycle to the existing session
summary. After many cycles in a long session the summary grows without bound, consuming an
increasing share of the context window on every turn.

The previous fix (`_trim_summary()`) solved this with a hard paragraph-cut: keep the last 8
paragraphs, discard the rest. This loses information — earlier session context ("we decided
not to do X") is silently dropped.

**Better solution:** When the summary exceeds the word threshold, call the LLM to re-summarise
the entire summary into a compact form. All information is preserved at reduced size.

---

## Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| Trigger threshold | 600 words (unchanged) | ~6–10 consolidation cycles; LLM cost is worth it at this scale |
| Output budget | Fixed 8 sentences | Meta-consolidation is a safety valve, not a scaling mechanism; stable size is preferable |
| System prompt | Own prompt (separate from `_CONSOLIDATION_SYSTEM`) | Task is different: compress an existing summary, not summarise raw conversation |
| On LLM failure | Graceful degradation — save oversized summary unchanged | Consistent with rest of error handling; large summary beats data loss |
| Code reuse | Extract `_call_llm()` shared helper | Eliminates try/except duplication between normal and meta consolidation |

---

## Architecture

### New constants (`squidbot/core/memory.py`)

```python
_META_CONSOLIDATION_SYSTEM = (
    "You are a memory consolidation assistant. "
    "You are given an existing session summary that has grown too long. "
    "Compress it into a shorter summary that retains all facts, decisions, and context. "
    "Output only the summary text — no preamble, no commentary, no formatting."
)

_META_CONSOLIDATION_PROMPT = (
    "The following is a session summary that has grown too long and needs to be compressed.\n\n"
    "{summary}\n\n"
    "Rewrite this as a compact summary of approximately {sentences} sentences. "
    "Retain all facts, decisions, and context. Do not discard any information."
)

_META_SUMMARY_WORD_LIMIT = 600   # trigger: words in updated summary
_META_SUMMARY_SENTENCES = 8      # fixed output budget
```

### Removed

- `_SUMMARY_WORD_LIMIT`, `_SUMMARY_KEEP_PARAGRAPHS` constants
- `_trim_summary(text: str) -> str` module-level function
- `updated = _trim_summary(updated)` call in `_consolidate()`
- Two tests: `test_session_summary_capped_when_exceeding_word_limit`,
  `test_session_summary_not_trimmed_when_under_word_limit`

### New methods on `MemoryManager`

**`_call_llm(self, messages: list[Message]) -> str | None`**

Shared LLM stream helper. Streams response, joins chunks, returns stripped text.
Returns `None` on any exception or empty response. Logs warning on exception.
Replaces the inline try/except block currently in `_consolidate()`.

Precondition: caller has already verified `self._llm is not None`.

```python
async def _call_llm(self, messages: list[Message]) -> str | None:
    llm = self._llm
    assert llm is not None  # noqa: S101
    try:
        chunks: list[str] = []
        async for chunk in await llm.chat(messages, []):
            if isinstance(chunk, str):
                chunks.append(chunk)
        result = "".join(chunks).strip()
        return result or None
    except Exception as e:
        from loguru import logger  # noqa: PLC0415
        logger.warning("LLM call failed: {}", e)
        return None
```

**`_maybe_meta_consolidate(self, summary: str) -> str`**

Checks word count. If within limit, returns summary unchanged (fast path, no LLM call).
Otherwise calls `_call_llm` with meta-consolidation messages.
Returns LLM result on success, original summary on failure/empty response.

```python
async def _maybe_meta_consolidate(self, summary: str) -> str:
    if len(summary.split()) <= _META_SUMMARY_WORD_LIMIT:
        return summary
    messages = [
        Message(role="system", content=_META_CONSOLIDATION_SYSTEM),
        Message(role="user", content=_META_CONSOLIDATION_PROMPT.format(
            summary=summary, sentences=_META_SUMMARY_SENTENCES
        )),
    ]
    result = await self._call_llm(messages)
    return result if result else summary
```

### Changes to `_consolidate()`

1. Replace inline try/except LLM block with `await self._call_llm(summary_messages)`
2. Replace `updated = _trim_summary(updated)` with `updated = await self._maybe_meta_consolidate(updated)`

The `assert llm is not None` guard moves into `_call_llm`; `_consolidate()` keeps its own
guard for the early-exit check (`self._llm is not None` in `build_messages`).

---

## Data Flow

```
_consolidate() called
  │
  ├─ build history_text from to_summarize
  ├─ call _call_llm(summary_messages)  →  summary: str | None
  │     None? → return recent (no change)
  │
  ├─ load existing session_summary
  ├─ updated = existing + "\n\n" + summary
  │
  ├─ _maybe_meta_consolidate(updated)
  │     ≤ 600 words? → return unchanged  (fast path)
  │     > 600 words? → _call_llm(meta_messages)
  │           success? → return compressed summary
  │           None?    → return updated unchanged  (graceful degradation)
  │
  └─ save_session_summary(updated) + save_consolidated_cursor
```

---

## Tests (`tests/core/test_memory.py`)

Five new tests replace the two removed trim tests:

| Test | What it verifies |
|------|-----------------|
| `test_call_llm_returns_text_on_success` | `_call_llm` returns joined chunks |
| `test_call_llm_returns_none_on_exception` | `_call_llm` returns `None` and logs warning on exception |
| `test_call_llm_returns_none_on_empty_response` | `_call_llm` returns `None` when LLM yields empty string |
| `test_meta_consolidation_triggered_above_word_limit` | LLM called, compressed summary saved when > 600 words |
| `test_meta_consolidation_not_triggered_below_word_limit` | No extra LLM call when summary ≤ 600 words |
| `test_meta_consolidation_failure_keeps_original_summary` | Oversized summary saved unchanged when `_call_llm` returns `None` |

Existing `_consolidate()` tests remain green — no behaviour change for normal-sized summaries.

---

## Files Changed

| File | Change |
|------|--------|
| `squidbot/core/memory.py` | Remove `_trim_summary` + constants; add `_META_*` constants, `_call_llm`, `_maybe_meta_consolidate`; refactor `_consolidate` |
| `tests/core/test_memory.py` | Remove 2 trim tests; add 6 new tests |

No port changes. No new files. No migration needed.
