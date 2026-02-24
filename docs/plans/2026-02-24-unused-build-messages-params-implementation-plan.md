# Remove Unused `build_messages` Parameters Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove unused `channel` and `sender_id` parameters from `MemoryManager.build_messages()`.

**Architecture:** Simple API cleanup — remove parameters from signature and update all callsites. No behavioral changes.

**Tech Stack:** Python 3.14, pytest, mypy, ruff

---

## Task 1: Update `build_messages()` signature in memory.py

**Files:**
- Modify: `squidbot/core/memory.py:164-185`

**Step 1: Update the signature and docstring**

Replace lines 164-185 in `squidbot/core/memory.py`:

```python
    async def build_messages(
        self,
        user_message: str,
        system_prompt: str,
    ) -> list[Message]:
        """
        Construct the full message list for an LLM call.

        Layout: [system_prompt + memory + summary + skills + optional warning]
                + [labelled_history] + [user_message]

        Args:
            user_message: The current user input.
            system_prompt: The base system prompt (AGENTS.md content).

        Returns:
            Ordered list of messages ready to send to the LLM.
        """
```

**Step 2: Run mypy to verify type errors at callsites**

Run: `uv run mypy squidbot/`
Expected: Type errors at callsites showing the extra arguments

---

## Task 2: Update callsite in agent.py

**Files:**
- Modify: `squidbot/core/agent.py:107-112`

**Step 1: Remove channel and sender_id arguments**

Replace lines 107-112 in `squidbot/core/agent.py`:

```python
        messages = await self._memory.build_messages(
            user_message=user_message,
            system_prompt=self._system_prompt,
        )
```

**Step 2: Run mypy to verify this callsite is fixed**

Run: `uv run mypy squidbot/core/agent.py`
Expected: No errors for this file

---

## Task 3: Update all test calls in test_memory.py

**Files:**
- Modify: `tests/core/test_memory.py` (multiple lines)

**Step 1: Update all `build_messages()` calls**

Replace all occurrences of:
```python
await manager.build_messages("cli", "local", "Hello", "You are a bot.")
```
With:
```python
await manager.build_messages("Hello", "You are a bot.")
```

Lines to update (replace first two positional args with nothing):
- Line 76: `("cli", "local", "Hello", "You are a bot.")` → `("Hello", "You are a bot.")`
- Line 88: `("cli", "local", "Hello", "You are a bot.")` → `("Hello", "You are a bot.")`
- Line 96: `("cli", "local", "Hello", "You are a bot.")` → `("Hello", "You are a bot.")`
- Line 104: `("cli", "local", "Hello", "You are a bot.")` → `("Hello", "You are a bot.")`
- Line 115: `("cli", "local", "follow up", "You are a bot.")` → `("follow up", "You are a bot.")`
- Line 140: `("cli", "alex", "what's up?", "You are helpful.")` → `("what's up?", "You are helpful.")`
- Line 153: `("matrix", "@alex:matrix.org", "hello", "sys")` → `("hello", "sys")`
- Line 164: `("cli", "local", "hello", "sys")` → `("hello", "sys")`
- Line 186: `("cli", "local", "hi", "sys")` → `("hi", "sys")`
- Line 197: `("matrix", "local", "hi", "sys")` → `("hi", "sys")`
- Line 207: `("cli", "local", "hi", "sys")` → `("hi", "sys")`
- Line 239: `("cli", "local", "new", "sys")` → `("new", "sys")`
- Line 255: `("cli", "local", "new", "sys")` → `("new", "sys")`
- Line 273: `("cli", "local", "new", "sys")` → `("new", "sys")`
- Line 290: `("cli", "local", "new", "sys")` → `("new", "sys")`
- Line 307: `("cli", "local", "new", "sys")` → `("new", "sys")`
- Line 326: `("cli", "local", "new", "sys")` → `("new", "sys")`
- Line 343: `("cli", "local", "new", "sys")` → `("new", "sys")`
- Line 357: `("cli", "local", "new", "sys")` → `("new", "sys")`
- Line 388: `("cli", "local", "new", "sys")` → `("new", "sys")`
- Line 408: `("cli", "local", "new", "sys")` → `("new", "sys")`
- Line 440: `("cli", "local", "new", "sys")` → `("new", "sys")`
- Line 468: `("cli", "local", f"user {i}", "sys")` → `(f"user {i}", "sys")`
- Line 542: `("cli", "local", "new", "sys")` → `("new", "sys")`
- Line 543: `("cli", "local", "new", "sys")` → `("new", "sys")`
- Line 579: `("cli", "local", "new", "sys")` → `("new", "sys")`
- Line 610: `("cli", "local", "new", "sys")` → `("new", "sys")`
- Line 631: `("cli", "local", "new", "sys")` → `("new", "sys")`
- Line 766: `("cli", "local", "new", "sys")` → `("new", "sys")`

**Step 2: Run tests to verify**

Run: `uv run pytest tests/core/test_memory.py -v`
Expected: All tests pass

---

## Task 4: Verify and commit

**Files:**
- All modified files

**Step 1: Run full verification**

Run: `uv run ruff check . && uv run mypy squidbot/ && uv run pytest`
Expected: All pass

**Step 2: Commit**

```bash
git add squidbot/core/memory.py squidbot/core/agent.py tests/core/test_memory.py
git commit -m "fix(memory): remove unused channel and sender_id params from build_messages"
```

---

## Summary

| Task | File | Change |
|------|------|--------|
| 1 | `squidbot/core/memory.py` | Remove `channel`, `sender_id` from signature |
| 2 | `squidbot/core/agent.py` | Update callsite |
| 3 | `tests/core/test_memory.py` | Update ~30 test calls |
| 4 | - | Verify and commit |

**Note:** `tests/adapters/tools/test_spawn.py` uses `AsyncMock(return_value=[])` without arguments, so no changes needed there.
