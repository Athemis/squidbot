# Memory System Small Fixes (Feature C) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Three small improvements to `MemoryManager._consolidate()`: dynamic summary budget, minimal system prompt for the consolidation LLM call, and caught `save_session_summary` failure.

**Architecture:** All changes are confined to `squidbot/core/memory.py` and `tests/core/test_memory.py`. No new files, no port changes.

**Tech Stack:** Python 3.14, pytest.

**Prerequisite:** Feature B (global memory redesign) must be implemented first. This plan assumes `save_session_summary` already exists and `_consolidate()` already uses it.

---

### Task 1: Dynamic summary budget

**Files:**
- Modify: `squidbot/core/memory.py`
- Modify: `tests/core/test_memory.py`

**Step 1: Write failing test**

Add to `tests/core/test_memory.py`:

```python
async def test_consolidation_prompt_scales_with_history_size(storage):
    """Larger histories get a larger sentence budget in the consolidation prompt."""
    captured_prompts: list[str] = []

    class CapturingLLM:
        async def chat(self, messages, tools, *, stream=True):
            captured_prompts.append(messages[-1].content)
            async def _gen():
                yield "summary"
            return _gen()

    # 50 messages → budget = max(5, 50 // 10) = 5
    manager_small = MemoryManager(
        storage=storage,
        consolidation_threshold=20,
        keep_recent_ratio=0.1,  # keep_recent = max(1, int(20*0.1)) = 2
        llm=CapturingLLM(),
    )
    storage2 = InMemoryStorage()
    manager_large = MemoryManager(
        storage=storage2,
        consolidation_threshold=20,
        keep_recent_ratio=0.1,
        llm=CapturingLLM(),
    )

    for i in range(25):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    for i in range(100):
        await storage2.append_message("s2", Message(role="user", content=f"msg {i}"))

    await manager_small.build_messages("s1", "sys", "new")
    await manager_large.build_messages("s2", "sys", "new")

    assert len(captured_prompts) == 2
    # Small: 25 - 2 = 23 messages → budget = max(5, 23//10) = 5 → "5 sentences"
    assert "5 sentences" in captured_prompts[0]
    # Large: 100 - 2 = 98 messages → budget = max(5, 98//10) = 9 → "9 sentences"
    assert "9 sentences" in captured_prompts[1]
```

Run: `uv run pytest tests/core/test_memory.py::test_consolidation_prompt_scales_with_history_size -v`
Expected: FAIL — prompt still uses hard-coded "2-5 sentences"

**Step 2: Update `_CONSOLIDATION_PROMPT` and `_consolidate()`**

In `squidbot/core/memory.py`, update `_CONSOLIDATION_PROMPT`:

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

In `_consolidate()`, compute `sentence_budget` before building the prompt:

```python
sentence_budget = max(5, len(to_summarize) // 10)
prompt = _CONSOLIDATION_PROMPT.format(history=history_text, sentences=sentence_budget)
```

**Step 3: Run memory tests**

Run: `uv run pytest tests/core/test_memory.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "fix(core): scale consolidation summary budget with history size"
```

---

### Task 2: Add system prompt to consolidation LLM call

**Files:**
- Modify: `squidbot/core/memory.py`
- Modify: `tests/core/test_memory.py`

**Step 1: Write failing test**

Add to `tests/core/test_memory.py`:

```python
async def test_consolidation_uses_system_prompt():
    """The consolidation LLM call includes a system message as first message."""
    received_messages: list = []

    class InspectingLLM:
        async def chat(self, messages, tools, *, stream=True):
            received_messages.extend(messages)
            async def _gen():
                yield "summary"
            return _gen()

    storage = InMemoryStorage()
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=3,
        keep_recent_ratio=0.34,
        llm=InspectingLLM(),
    )
    for i in range(4):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    await manager.build_messages("s1", "sys", "new")

    assert len(received_messages) >= 2
    assert received_messages[0].role == "system"
    assert "consolidation" in received_messages[0].content.lower()
```

Run: `uv run pytest tests/core/test_memory.py::test_consolidation_uses_system_prompt -v`
Expected: FAIL — first message is `user`, not `system`

**Step 2: Add `_CONSOLIDATION_SYSTEM` constant and update the LLM call**

In `squidbot/core/memory.py`, add after `_CONSOLIDATION_PROMPT`:

```python
_CONSOLIDATION_SYSTEM = (
    "You are a memory consolidation assistant. "
    "Your sole task is to produce concise, factual summaries of conversation history. "
    "Output only the summary text — no preamble, no commentary, no formatting."
)
```

In `_consolidate()`, update `summary_messages`:

```python
summary_messages = [
    Message(role="system", content=_CONSOLIDATION_SYSTEM),
    Message(role="user", content=prompt),
]
```

**Step 3: Run memory tests**

Run: `uv run pytest tests/core/test_memory.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "fix(core): add system prompt to consolidation LLM call"
```

---

### Task 3: Catch `save_session_summary` failure

**Files:**
- Modify: `squidbot/core/memory.py`
- Modify: `tests/core/test_memory.py`

**Step 1: Write failing test**

Add to `tests/core/test_memory.py`:

```python
async def test_consolidation_save_failure_is_caught():
    """If save_session_summary raises, the turn continues without crashing."""

    class FailingSaveStorage(InMemoryStorage):
        async def save_session_summary(self, session_id: str, content: str) -> None:
            raise OSError("disk full")

    storage = FailingSaveStorage()
    llm = ScriptedLLM("Summary: some content.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=3,
        keep_recent_ratio=0.34,
        llm=llm,
    )
    for i in range(4):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))

    # Should not raise — the save failure is swallowed
    messages = await manager.build_messages("s1", "sys", "new")
    # History is still returned (recent messages), cursor not advanced
    assert len(messages) >= 2


async def test_consolidation_cursor_not_advanced_if_save_fails():
    """Cursor stays at 0 if save_session_summary fails (consistent state)."""

    class FailingSaveStorage(InMemoryStorage):
        async def save_session_summary(self, session_id: str, content: str) -> None:
            raise OSError("disk full")

    storage = FailingSaveStorage()
    llm = ScriptedLLM("Summary.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=3,
        keep_recent_ratio=0.34,
        llm=llm,
    )
    for i in range(4):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    await manager.build_messages("s1", "sys", "new")
    cursor = await storage.load_consolidated_cursor("s1")
    assert cursor == 0  # not advanced
```

Run: `uv run pytest tests/core/test_memory.py::test_consolidation_save_failure_is_caught -v`
Expected: FAIL — exception propagates

**Step 2: Wrap save calls in `_consolidate()`**

In `squidbot/core/memory.py`, in `_consolidate()`, replace the save block:

```python
existing = await self._storage.load_session_summary(session_id)
updated = f"{existing}\n\n{summary}" if existing.strip() else summary
await self._storage.save_session_summary(session_id, updated)

new_cursor = len(history) - self._keep_recent
await self._storage.save_consolidated_cursor(session_id, new_cursor)
```

with:

```python
existing = await self._storage.load_session_summary(session_id)
updated = f"{existing}\n\n{summary}" if existing.strip() else summary
try:
    await self._storage.save_session_summary(session_id, updated)
    new_cursor = len(history) - self._keep_recent
    await self._storage.save_consolidated_cursor(session_id, new_cursor)
except Exception as e:
    from loguru import logger  # noqa: PLC0415
    logger.warning("Failed to save consolidation summary, skipping: {}", e)
    return recent
```

**Step 3: Run all memory tests**

Run: `uv run pytest tests/core/test_memory.py -v`
Expected: All PASS

**Step 4: Run full suite + lint + mypy**

```bash
uv run pytest -v
uv run ruff check .
uv run mypy squidbot/
```
Expected: All PASS, no errors

**Step 5: Commit**

```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "fix(core): catch save_session_summary failure in consolidation"
```
