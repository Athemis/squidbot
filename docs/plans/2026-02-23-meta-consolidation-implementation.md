# Meta-Consolidation of Session Summary — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the `_trim_summary()` paragraph-cut with meta-consolidation: when the session summary exceeds 600 words, call the LLM to compress it into ~8 sentences, preserving all information.

**Architecture:** All changes are confined to `squidbot/core/memory.py` and `tests/core/test_memory.py`. Extract a shared `_call_llm()` helper to eliminate the existing try/except duplication. Add `_maybe_meta_consolidate()` that calls it. Replace `_trim_summary()` call in `_consolidate()` with `_maybe_meta_consolidate()`. No port changes, no new files.

**Tech Stack:** Python 3.14, pytest, ruff, mypy.

**Design doc:** `docs/plans/2026-02-23-meta-consolidation-design.md`

**Prerequisite:** 355 tests pass on `main`. Confirm: `uv run pytest -q`

---

### Task 1: Extract `_call_llm()` helper and refactor `_consolidate()`

This task removes the inline try/except LLM block from `_consolidate()` and replaces it with a shared helper. No behaviour change — all existing tests must stay green.

**Files:**
- Modify: `squidbot/core/memory.py`
- Modify: `tests/core/test_memory.py`

**Step 1: Write three failing tests for `_call_llm()`**

Add after the last test in `tests/core/test_memory.py`:

```python
# ---------------------------------------------------------------------------
# _call_llm helper
# ---------------------------------------------------------------------------


async def test_call_llm_returns_text_on_success():
    """_call_llm joins streamed chunks and returns stripped text."""
    storage = InMemoryStorage()
    llm = ScriptedLLM("  hello world  ")
    manager = MemoryManager(storage=storage, llm=llm)
    messages = [Message(role="user", content="ping")]
    result = await manager._call_llm(messages)
    assert result == "hello world"


async def test_call_llm_returns_none_on_exception():
    """_call_llm returns None and logs a warning when the LLM raises."""

    class FailingLLM:
        async def chat(self, messages, tools, *, stream=True):
            raise RuntimeError("network error")

    storage = InMemoryStorage()
    manager = MemoryManager(storage=storage, llm=FailingLLM())
    result = await manager._call_llm([Message(role="user", content="ping")])
    assert result is None


async def test_call_llm_returns_none_on_empty_response():
    """_call_llm returns None when the LLM yields only whitespace."""
    storage = InMemoryStorage()
    llm = ScriptedLLM("   ")
    manager = MemoryManager(storage=storage, llm=llm)
    result = await manager._call_llm([Message(role="user", content="ping")])
    assert result is None
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/core/test_memory.py::test_call_llm_returns_text_on_success tests/core/test_memory.py::test_call_llm_returns_none_on_exception tests/core/test_memory.py::test_call_llm_returns_none_on_empty_response -v`
Expected: FAIL — `_call_llm` does not exist yet

**Step 3: Add `_call_llm()` to `MemoryManager`**

Add this method to `MemoryManager` after `persist_exchange()` and before `_consolidate()`:

```python
async def _call_llm(self, messages: list[Message]) -> str | None:
    """
    Call the LLM with the given messages and return the full response text.

    Streams the response, joins all text chunks, and returns the stripped result.
    Returns None if the LLM raises an exception or yields an empty response.
    Logs a warning on exception.

    Precondition: self._llm is not None (caller must verify).

    Args:
        messages: The messages to send to the LLM.

    Returns:
        Stripped response text, or None on failure or empty response.
    """
    llm = self._llm
    assert llm is not None  # noqa: S101 — narrowing for type checker
    try:
        chunks: list[str] = []
        response_stream = await llm.chat(messages, [])
        async for chunk in response_stream:
            if isinstance(chunk, str):
                chunks.append(chunk)
        result = "".join(chunks).strip()
        return result or None
    except Exception as e:
        from loguru import logger  # noqa: PLC0415

        logger.warning("LLM call failed: {}", e)
        return None
```

**Step 4: Run the three new tests**

Run: `uv run pytest tests/core/test_memory.py::test_call_llm_returns_text_on_success tests/core/test_memory.py::test_call_llm_returns_none_on_exception tests/core/test_memory.py::test_call_llm_returns_none_on_empty_response -v`
Expected: PASS

**Step 5: Refactor `_consolidate()` to use `_call_llm()`**

In `_consolidate()`, replace the existing try/except LLM block (the section that builds `summary_messages`, calls `llm.chat`, and handles exceptions) with:

```python
        # Call LLM for summary (self._llm is non-None; caller guarantees this)
        sentence_budget = max(5, len(to_summarize) // 10)
        prompt = _CONSOLIDATION_PROMPT.format(history=history_text, sentences=sentence_budget)
        summary_messages = [
            Message(role="system", content=_CONSOLIDATION_SYSTEM),
            Message(role="user", content=prompt),
        ]
        summary = await self._call_llm(summary_messages)
        if not summary:
            return recent
```

The `assert llm is not None` and the old try/except block are removed — `_call_llm` handles both.

**Step 6: Run all memory tests**

Run: `uv run pytest tests/core/test_memory.py -v`
Expected: all PASS (no behaviour change)

**Step 7: Run full suite + lint + type-check**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy squidbot/
```
Expected: 358 passed, no errors.

**Step 8: Commit**

```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "refactor(core): extract _call_llm helper, remove inline try/except in _consolidate"
```

---

### Task 2: Add `_maybe_meta_consolidate()` and constants, remove `_trim_summary()`

This task adds meta-consolidation and removes the old paragraph-cut approach.

**Files:**
- Modify: `squidbot/core/memory.py`
- Modify: `tests/core/test_memory.py`

**Step 1: Write three failing tests for meta-consolidation**

Add after the `_call_llm` tests in `tests/core/test_memory.py`:

```python
# ---------------------------------------------------------------------------
# _maybe_meta_consolidate: meta-consolidation of session summary
# ---------------------------------------------------------------------------


async def test_meta_consolidation_not_triggered_below_word_limit():
    """No extra LLM call when summary is within the word limit."""
    call_count = 0

    class CountingLLM:
        async def chat(self, messages, tools, *, stream=True):
            nonlocal call_count
            call_count += 1

            async def _gen():
                yield "summary"

            return _gen()

    storage = InMemoryStorage()
    manager = MemoryManager(storage=storage, llm=CountingLLM())
    # Short summary — well under 600 words
    short_summary = "This is a short session summary."
    result = await manager._maybe_meta_consolidate(short_summary)
    # No LLM call, summary returned unchanged
    assert result == short_summary
    assert call_count == 0


async def test_meta_consolidation_triggered_above_word_limit():
    """LLM is called to compress summary when > 600 words."""
    storage = InMemoryStorage()
    llm = ScriptedLLM("Compressed meta summary.")
    manager = MemoryManager(storage=storage, llm=llm)
    # Build a summary over 600 words
    fat_summary = " ".join(["word"] * 650)
    result = await manager._maybe_meta_consolidate(fat_summary)
    assert result == "Compressed meta summary."


async def test_meta_consolidation_failure_keeps_original_summary():
    """When LLM fails, the original oversized summary is returned unchanged."""

    class FailingLLM:
        async def chat(self, messages, tools, *, stream=True):
            raise RuntimeError("timeout")

    storage = InMemoryStorage()
    manager = MemoryManager(storage=storage, llm=FailingLLM())
    fat_summary = " ".join(["word"] * 650)
    result = await manager._maybe_meta_consolidate(fat_summary)
    # Original returned — no data loss
    assert result == fat_summary
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/core/test_memory.py::test_meta_consolidation_not_triggered_below_word_limit tests/core/test_memory.py::test_meta_consolidation_triggered_above_word_limit tests/core/test_memory.py::test_meta_consolidation_failure_keeps_original_summary -v`
Expected: FAIL — `_maybe_meta_consolidate` does not exist yet

**Step 3: Add new constants to `squidbot/core/memory.py`**

Replace the existing soft-cap constants block:

Old (around line 41):
```python
# Soft-cap trigger: if session summary exceeds this word count, trim to
# the most recent _SUMMARY_KEEP_PARAGRAPHS paragraphs. Not a hard upper bound —
# kept paragraphs may individually exceed the limit.
_SUMMARY_WORD_LIMIT = 600
_SUMMARY_KEEP_PARAGRAPHS = 8
```

New:
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

_META_SUMMARY_WORD_LIMIT = 600
_META_SUMMARY_SENTENCES = 8
```

**Step 4: Remove `_trim_summary()` function**

Delete the entire `_trim_summary()` function (the module-level function after the constants block).

**Step 5: Add `_maybe_meta_consolidate()` to `MemoryManager`**

Add this method after `_call_llm()` and before `_consolidate()`:

```python
async def _maybe_meta_consolidate(self, summary: str) -> str:
    """
    Compress the session summary via LLM if it exceeds the word limit.

    If the summary is within _META_SUMMARY_WORD_LIMIT words, returns it unchanged
    (fast path, no LLM call). Otherwise calls the LLM with a meta-consolidation
    prompt to produce a compressed version of approximately _META_SUMMARY_SENTENCES
    sentences. On LLM failure, returns the original summary unchanged (graceful
    degradation — data loss avoided at the cost of a large summary).

    Precondition: self._llm is not None (caller must verify).

    Args:
        summary: The current session summary text.

    Returns:
        Compressed summary text, or original summary if within limit or on failure.
    """
    if len(summary.split()) <= _META_SUMMARY_WORD_LIMIT:
        return summary
    messages = [
        Message(role="system", content=_META_CONSOLIDATION_SYSTEM),
        Message(
            role="user",
            content=_META_CONSOLIDATION_PROMPT.format(
                summary=summary,
                sentences=_META_SUMMARY_SENTENCES,
            ),
        ),
    ]
    result = await self._call_llm(messages)
    return result if result else summary
```

**Step 6: Wire `_maybe_meta_consolidate()` into `_consolidate()`**

In `_consolidate()`, replace:
```python
        updated = _trim_summary(updated)
```

With:
```python
        updated = await self._maybe_meta_consolidate(updated)
```

**Step 7: Remove the two old trim tests from `tests/core/test_memory.py`**

Delete these two test functions entirely:
- `test_session_summary_capped_when_exceeding_word_limit`
- `test_session_summary_not_trimmed_when_under_word_limit`

**Step 8: Run all memory tests**

Run: `uv run pytest tests/core/test_memory.py -v`
Expected: all PASS (three new tests pass, old trim tests gone)

**Step 9: Run full suite + lint + type-check**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy squidbot/
```
Expected: all green, no errors.

**Step 10: Commit**

```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "feat(core): replace trim-based summary cap with LLM meta-consolidation"
```
