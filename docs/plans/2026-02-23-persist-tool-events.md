# Persist Tool Events Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Write `tool_call` and `tool_result` messages to the JSONL after every tool execution so the agent can recall past tool usage via `search_history`.

**Architecture:** Extend `Message.role` with two new literal values (`"tool_call"`, `"tool_result"`). After each tool execution in `AgentLoop.run()`, call a new `MemoryManager.append_tool_event()` helper that writes both messages to JSONL. Filter those roles out in `build_messages` before LLM context is built and before cursor arithmetic. Extend `search_history` to include the new roles.

**Tech Stack:** Python 3.14, dataclasses, pytest, ruff, mypy

---

### Task 1: Extend `Message.role` Literal

**Files:**
- Modify: `squidbot/core/models.py:38`
- Test: `tests/core/test_models.py` *(create if missing — see below)*

**Step 1: Verify there is no existing test for `Message.role`**

Run:
```bash
uv run pytest tests/ -k "message" -v 2>&1 | head -30
```

There is no `tests/core/test_models.py`. We will add the tests inline in `test_memory.py` since `Message` is a pure dataclass — but the type change alone is tested implicitly by all tests that create `Message(role="tool_call", ...)`. The mypy check is the real gate.

**Step 2: Write the failing mypy check**

Before the change, this assignment should fail mypy:
```python
# squidbot/core/models.py line 38 — current:
role: Literal["system", "user", "assistant", "tool"]
```

Verify mypy currently rejects `"tool_call"`:
```bash
python -c "
from squidbot.core.models import Message
m = Message(role='tool_call', content='test')
print(m)
" 2>&1
```
Expected: no runtime error (Literal is not enforced at runtime), but mypy would flag it.

**Step 3: Edit `squidbot/core/models.py`**

Change line 38:
```python
# OLD
role: Literal["system", "user", "assistant", "tool"]

# NEW
role: Literal["system", "user", "assistant", "tool", "tool_call", "tool_result"]
```

**Step 4: Run mypy and ruff**

```bash
uv run mypy squidbot/
uv run ruff check .
```
Expected: no new errors.

**Step 5: Commit**

```bash
git add squidbot/core/models.py
git commit -m "feat(models): extend Message.role with tool_call and tool_result"
```

---

### Task 2: Add `append_tool_event` to `MemoryManager`

**Files:**
- Modify: `squidbot/core/memory.py` (add method after `persist_exchange`)
- Test: `tests/core/test_memory.py` (add tests at end of file)

**Step 1: Write the failing test first**

Add to the end of `tests/core/test_memory.py`:

```python
async def test_append_tool_event_writes_two_messages(storage):
    manager = MemoryManager(storage=storage)
    await manager.append_tool_event(
        session_id="cli:local",
        call_text="shell(cmd='ls -la')",
        result_text="total 8\ndrwxr-xr-x 2 user user",
    )
    history = await storage.load_history("cli:local")
    assert len(history) == 2
    assert history[0].role == "tool_call"
    assert history[0].content == "shell(cmd='ls -la')"
    assert history[1].role == "tool_result"
    assert history[1].content == "total 8\ndrwxr-xr-x 2 user user"


async def test_append_tool_event_messages_have_timestamps(storage):
    manager = MemoryManager(storage=storage)
    await manager.append_tool_event(
        session_id="cli:local",
        call_text="read_file(path='/tmp/x')",
        result_text="file contents",
    )
    history = await storage.load_history("cli:local")
    assert history[0].timestamp is not None
    assert history[1].timestamp is not None
```

**Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/core/test_memory.py::test_append_tool_event_writes_two_messages -v
```
Expected: `FAILED` — `AttributeError: 'MemoryManager' object has no attribute 'append_tool_event'`

**Step 3: Add `append_tool_event` to `MemoryManager`**

Insert after the `persist_exchange` method in `squidbot/core/memory.py` (after line 183):

```python
async def append_tool_event(
    self,
    session_id: str,
    call_text: str,
    result_text: str,
) -> None:
    """
    Persist a tool call and its result as two searchable JSONL messages.

    These messages use the custom roles "tool_call" and "tool_result" which
    are never sent to the LLM API — they are filtered out in build_messages.
    They are searchable via search_history.

    Args:
        session_id: Unique session identifier.
        call_text: Human-readable call string, e.g. "shell(cmd='ls -la')".
        result_text: Tool output (pre-truncated by the caller).
    """
    await self._storage.append_message(
        session_id, Message(role="tool_call", content=call_text)
    )
    await self._storage.append_message(
        session_id, Message(role="tool_result", content=result_text)
    )
```

**Step 4: Run tests**

```bash
uv run pytest tests/core/test_memory.py::test_append_tool_event_writes_two_messages tests/core/test_memory.py::test_append_tool_event_messages_have_timestamps -v
```
Expected: both PASS.

**Step 5: Run full test suite and mypy**

```bash
uv run pytest tests/core/test_memory.py -v
uv run mypy squidbot/core/memory.py
```
Expected: all pass.

**Step 6: Commit**

```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "feat(memory): add append_tool_event helper"
```

---

### Task 3: Filter `tool_call`/`tool_result` in `build_messages`

**Files:**
- Modify: `squidbot/core/memory.py` (`build_messages` method, around line 118)
- Test: `tests/core/test_memory.py`

**Background on cursor arithmetic:** The cursor is a count of messages in filtered history (no tool_call/tool_result). Since these roles were never in the JSONL before this change, existing cursors remain valid. After this change, the filter must happen *before* the cursor threshold check so that tool events don't inflate the count.

**Step 1: Write failing test first**

Add to `tests/core/test_memory.py`:

```python
async def test_build_messages_filters_tool_events_from_llm_context(storage):
    """tool_call and tool_result messages must not appear in the LLM message list."""
    manager = MemoryManager(storage=storage)
    await storage.append_message("cli:local", Message(role="user", content="do something"))
    await storage.append_message("cli:local", Message(role="tool_call", content="shell(cmd='ls')"))
    await storage.append_message("cli:local", Message(role="tool_result", content="file.txt"))
    await storage.append_message("cli:local", Message(role="assistant", content="Done."))

    messages = await manager.build_messages("cli:local", "sys", "next")
    roles = [m.role for m in messages]
    assert "tool_call" not in roles
    assert "tool_result" not in roles
    # user + assistant history + system + new user = 4
    assert len(messages) == 4


async def test_tool_events_do_not_inflate_consolidation_threshold(storage):
    """Tool events in JSONL must not count toward the consolidation threshold."""
    llm = ScriptedLLM("Summary.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=4,
        keep_recent_ratio=0.25,  # keep_recent = 1
        llm=llm,
    )
    # 3 user/assistant messages + many tool events = raw count 9, filtered count 3
    for i in range(3):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
        await storage.append_message("s1", Message(role="tool_call", content=f"call {i}"))
        await storage.append_message("s1", Message(role="tool_result", content=f"result {i}"))

    messages = await manager.build_messages("s1", "sys", "new")
    # 3 user messages in history (under threshold of 4) → no consolidation
    # system + 3 history + new user = 5 total
    assert len(messages) == 5
    doc = await storage.load_session_summary("s1")
    assert doc == ""  # no consolidation fired
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/core/test_memory.py::test_build_messages_filters_tool_events_from_llm_context tests/core/test_memory.py::test_tool_events_do_not_inflate_consolidation_threshold -v
```
Expected: both FAIL (tool_call/tool_result appear in messages, wrong count).

**Step 3: Edit `build_messages` in `squidbot/core/memory.py`**

After the `load_history` call (current line 118) and before the cursor load, insert the filter:

```python
# Current code around line 118-124:
history = await self._storage.load_history(session_id)

# Load cursor once; used for trigger check, warning check, and consolidation
cursor = await self._storage.load_consolidated_cursor(session_id)

# Consolidate history if unconsolidated messages exceed threshold and LLM available
if len(history) - cursor > self._consolidation_threshold and self._llm is not None:
```

Change to:

```python
history = await self._storage.load_history(session_id)

# Filter tool events before cursor arithmetic — these roles are never sent to the LLM
# and must not inflate consolidation thresholds or appear in the LLM context.
history = [m for m in history if m.role not in ("tool_call", "tool_result")]

# Load cursor once; used for trigger check, warning check, and consolidation
cursor = await self._storage.load_consolidated_cursor(session_id)

# Consolidate history if unconsolidated messages exceed threshold and LLM available
if len(history) - cursor > self._consolidation_threshold and self._llm is not None:
```

**Step 4: Run the new tests**

```bash
uv run pytest tests/core/test_memory.py::test_build_messages_filters_tool_events_from_llm_context tests/core/test_memory.py::test_tool_events_do_not_inflate_consolidation_threshold -v
```
Expected: both PASS.

**Step 5: Run the full memory test suite**

```bash
uv run pytest tests/core/test_memory.py -v
```
Expected: all pass. If `test_build_messages_includes_history` fails, check that it only uses `user`/`assistant` messages (it does — no change needed there).

**Step 6: Run mypy and ruff**

```bash
uv run mypy squidbot/core/memory.py
uv run ruff check squidbot/core/memory.py
```

**Step 7: Commit**

```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "feat(memory): filter tool_call/tool_result from LLM context in build_messages"
```

---

### Task 4: Write tool events in `AgentLoop.run()`

**Files:**
- Modify: `squidbot/core/agent.py`
- Test: `tests/core/test_agent.py`

**Step 1: Write failing tests first**

Add to `tests/core/test_agent.py`:

```python
async def test_tool_events_written_to_storage_after_tool_call(storage, memory):
    """After a tool call, tool_call and tool_result messages are in storage."""
    tool_call = ToolCall(id="tc_1", name="echo", arguments={"text": "hello"})
    llm = ScriptedLLM([[tool_call], "Done."])
    registry = ToolRegistry()
    registry.register(EchoTool())
    channel = CollectingChannel()
    loop = AgentLoop(llm=llm, memory=memory, registry=registry, system_prompt="sys")

    await loop.run(SESSION, "run echo", channel)

    history = await storage.load_history(SESSION.id)
    roles = [m.role for m in history]
    assert "tool_call" in roles
    assert "tool_result" in roles


async def test_tool_call_text_format(storage, memory):
    """tool_call content is formatted as 'name(key=value, ...)'."""
    tool_call = ToolCall(id="tc_1", name="echo", arguments={"text": "world"})
    llm = ScriptedLLM([[tool_call], "Done."])
    registry = ToolRegistry()
    registry.register(EchoTool())
    channel = CollectingChannel()
    loop = AgentLoop(llm=llm, memory=memory, registry=registry, system_prompt="sys")

    await loop.run(SESSION, "run echo", channel)

    history = await storage.load_history(SESSION.id)
    tool_call_msg = next(m for m in history if m.role == "tool_call")
    assert tool_call_msg.content == "echo(text='world')"


async def test_tool_result_content_truncated_at_2000_chars(storage, memory):
    """Tool results longer than 2000 characters are truncated with [truncated] marker."""

    class LongOutputTool:
        name = "long_output"
        description = "Returns a very long string"
        parameters = {"type": "object", "properties": {}}

        async def execute(self, **_) -> ToolResult:
            return ToolResult(tool_call_id="", content="x" * 3000)

    tool_call = ToolCall(id="tc_1", name="long_output", arguments={})
    llm = ScriptedLLM([[tool_call], "Done."])
    registry = ToolRegistry()
    registry.register(LongOutputTool())
    channel = CollectingChannel()
    loop = AgentLoop(llm=llm, memory=memory, registry=registry, system_prompt="sys")

    await loop.run(SESSION, "get long output", channel)

    history = await storage.load_history(SESSION.id)
    tool_result_msg = next(m for m in history if m.role == "tool_result")
    assert len(tool_result_msg.content) <= 2001 + len("\n[truncated]")
    assert tool_result_msg.content.endswith("\n[truncated]")


async def test_tool_events_not_sent_to_channel(storage, memory):
    """tool_call/tool_result messages do not appear as channel output."""
    tool_call = ToolCall(id="tc_1", name="echo", arguments={"text": "hi"})
    llm = ScriptedLLM([[tool_call], "Done."])
    registry = ToolRegistry()
    registry.register(EchoTool())
    channel = CollectingChannel()
    loop = AgentLoop(llm=llm, memory=memory, registry=registry, system_prompt="sys")

    await loop.run(SESSION, "echo hi", channel)

    # Only the final text reply is sent to the channel
    assert channel.sent == ["Done."]
```

**Step 2: Verify tests fail**

```bash
uv run pytest tests/core/test_agent.py::test_tool_events_written_to_storage_after_tool_call tests/core/test_agent.py::test_tool_call_text_format tests/core/test_agent.py::test_tool_result_content_truncated_at_2000_chars tests/core/test_agent.py::test_tool_events_not_sent_to_channel -v
```
Expected: all 4 FAIL (`tool_call` not in roles, format wrong, etc.)

**Step 3: Add constant and hook in `squidbot/core/agent.py`**

After line 27 (`MAX_TOOL_ROUNDS = 20`), add:

```python
# Maximum characters stored for a tool result in JSONL history.
# Prevents bloat from large file reads or shell output.
_TOOL_RESULT_MAX_CHARS = 2000
```

Inside the `for tc in tool_calls:` loop (currently lines 156–175), after the `messages.append(Message(role="tool", ...))` call (currently line 169–175), add the persistence call:

```python
# Current end of the for loop:
            messages.append(
                Message(
                    role="tool",
                    content=result.content,
                    tool_call_id=tc.id,
                )
            )

# ADD after that append:
            call_text = (
                f"{tc.name}("
                + ", ".join(f"{k}={v!r}" for k, v in tc.arguments.items())
                + ")"
            )
            result_text = result.content
            if len(result_text) > _TOOL_RESULT_MAX_CHARS:
                result_text = result_text[:_TOOL_RESULT_MAX_CHARS] + "\n[truncated]"
            await self._memory.append_tool_event(
                session_id=session.id,
                call_text=call_text,
                result_text=result_text,
            )
```

**Step 4: Run the new tests**

```bash
uv run pytest tests/core/test_agent.py::test_tool_events_written_to_storage_after_tool_call tests/core/test_agent.py::test_tool_call_text_format tests/core/test_agent.py::test_tool_result_content_truncated_at_2000_chars tests/core/test_agent.py::test_tool_events_not_sent_to_channel -v
```
Expected: all 4 PASS.

**Step 5: Run full agent test suite**

```bash
uv run pytest tests/core/test_agent.py -v
```
Expected: all pass.

**Step 6: Run mypy and ruff**

```bash
uv run mypy squidbot/core/agent.py
uv run ruff check squidbot/core/agent.py
```

**Step 7: Commit**

```bash
git add squidbot/core/agent.py tests/core/test_agent.py
git commit -m "feat(agent): persist tool_call and tool_result events after each tool execution"
```

---

### Task 5: Extend `search_history` to include tool events

**Files:**
- Modify: `squidbot/adapters/tools/search_history.py`
- Test: `tests/adapters/tools/test_search_history.py`

**Current behaviour:** only `role in ("user", "assistant")` are searched and shown.
**New behaviour:** `"tool_call"` and `"tool_result"` are also searchable and displayed with `TOOL CALL` / `TOOL RESULT` labels.

**Step 1: Write failing tests first**

Add to `tests/adapters/tools/test_search_history.py`:

```python
async def test_tool_call_messages_are_searchable(memory: JsonlMemory, tool: SearchHistoryTool):
    """tool_call messages with matching content appear in search results."""
    await memory.append_message(
        "cli:local",
        Message(role="tool_call", content="shell(cmd='git log --oneline')"),
    )
    result = await tool.execute(query="git log")
    assert result.is_error is False
    assert "git log" in result.content


async def test_tool_result_messages_are_searchable(memory: JsonlMemory, tool: SearchHistoryTool):
    """tool_result messages with matching content appear in search results."""
    await memory.append_message(
        "cli:local",
        Message(role="tool_result", content="abc1234 fix: typo in README"),
    )
    result = await tool.execute(query="fix: typo")
    assert result.is_error is False
    assert "fix: typo" in result.content


async def test_tool_call_shown_with_tool_call_label(memory: JsonlMemory, tool: SearchHistoryTool):
    """Matching tool_call messages display with 'TOOL CALL' label."""
    await memory.append_message(
        "cli:local",
        Message(role="tool_call", content="read_file(path='/tmp/notes.txt')"),
    )
    result = await tool.execute(query="notes.txt")
    assert "TOOL CALL" in result.content


async def test_tool_result_shown_with_tool_result_label(
    memory: JsonlMemory, tool: SearchHistoryTool
):
    """Matching tool_result messages display with 'TOOL RESULT' label."""
    await memory.append_message(
        "cli:local",
        Message(role="tool_result", content="contents of notes"),
    )
    result = await tool.execute(query="contents of notes")
    assert "TOOL RESULT" in result.content


async def test_tool_events_appear_as_context_for_surrounding_match(
    memory: JsonlMemory, tool: SearchHistoryTool
):
    """tool_call/tool_result adjacent to a matching user message appear as context."""
    await memory.append_message(
        "cli:local", Message(role="user", content="Run git status please")
    )
    await memory.append_message(
        "cli:local", Message(role="tool_call", content="shell(cmd='git status')")
    )
    await memory.append_message(
        "cli:local", Message(role="tool_result", content="On branch main, nothing to commit")
    )
    result = await tool.execute(query="git status")
    assert result.is_error is False
    # At least the user message and tool call should appear
    assert "git status" in result.content.lower()
```

**Step 2: Verify tests fail**

```bash
uv run pytest tests/adapters/tools/test_search_history.py::test_tool_call_messages_are_searchable tests/adapters/tools/test_search_history.py::test_tool_result_messages_are_searchable tests/adapters/tools/test_search_history.py::test_tool_call_shown_with_tool_call_label tests/adapters/tools/test_search_history.py::test_tool_result_shown_with_tool_result_label -v
```
Expected: all FAIL.

**Step 3: Edit `squidbot/adapters/tools/search_history.py`**

There are two places to update:

**a) The match filter** (currently line 131):
```python
# OLD
if msg.role in ("user", "assistant") and msg.content and query in msg.content.lower():

# NEW
if msg.role in ("user", "assistant", "tool_call", "tool_result") and msg.content and query in msg.content.lower():
```

**b) The context display block** (currently lines 152–160):

```python
# OLD
            for offset in (-1, 0, 1):
                j = idx + offset
                if 0 <= j < len(all_messages):
                    _, ctx = all_messages[j]
                    if ctx.role not in ("user", "assistant") or not ctx.content:
                        continue
                    text = ctx.content[:300] + ("..." if len(ctx.content) > 300 else "")
                    role_label = ctx.role.upper()
                    if offset == 0:
                        lines.append(f"**{role_label}: {text}**")
                    else:
                        lines.append(f"{role_label}: {text}")

# NEW
            _SEARCHABLE_ROLES = {"user", "assistant", "tool_call", "tool_result"}
            _ROLE_LABELS = {
                "user": "USER",
                "assistant": "ASSISTANT",
                "tool_call": "TOOL CALL",
                "tool_result": "TOOL RESULT",
            }
            for offset in (-1, 0, 1):
                j = idx + offset
                if 0 <= j < len(all_messages):
                    _, ctx = all_messages[j]
                    if ctx.role not in _SEARCHABLE_ROLES or not ctx.content:
                        continue
                    text = ctx.content[:300] + ("..." if len(ctx.content) > 300 else "")
                    role_label = _ROLE_LABELS.get(ctx.role, ctx.role.upper())
                    if offset == 0:
                        lines.append(f"**{role_label}: {text}**")
                    else:
                        lines.append(f"{role_label}: {text}")
```

> Note: `_SEARCHABLE_ROLES` and `_ROLE_LABELS` can be module-level constants instead of loop-locals if preferred; either is fine.

**Step 4: Run the new tests**

```bash
uv run pytest tests/adapters/tools/test_search_history.py::test_tool_call_messages_are_searchable tests/adapters/tools/test_search_history.py::test_tool_result_messages_are_searchable tests/adapters/tools/test_search_history.py::test_tool_call_shown_with_tool_call_label tests/adapters/tools/test_search_history.py::test_tool_result_shown_with_tool_result_label tests/adapters/tools/test_search_history.py::test_tool_result_shown_with_tool_result_label -v
```
Expected: all PASS.

**Step 5: Verify existing test `test_tool_calls_excluded_from_search` still passes**

The existing test checks that `role="tool"` (the OpenAI-format role) is still excluded. That should still be true since we only added `"tool_call"` and `"tool_result"`.

```bash
uv run pytest tests/adapters/tools/test_search_history.py -v
```
Expected: all pass.

**Step 6: Run mypy and ruff**

```bash
uv run mypy squidbot/adapters/tools/search_history.py
uv run ruff check squidbot/adapters/tools/search_history.py
```

**Step 7: Also update the module docstring** in `search_history.py` — the first paragraph currently says "Only user and assistant messages are searchable":

```python
# OLD (line 6):
# Only user and assistant messages are searchable; tool calls and system
# messages are excluded from both search and output.

# NEW:
# User, assistant, tool_call, and tool_result messages are searchable.
# The low-level role="tool" (OpenAI API format) and system messages are excluded.
```

**Step 8: Commit**

```bash
git add squidbot/adapters/tools/search_history.py tests/adapters/tools/test_search_history.py
git commit -m "feat(search_history): include tool_call and tool_result roles in search and output"
```

---

### Task 6: Full verification pass

**Step 1: Run the entire test suite**

```bash
uv run pytest -v
```
Expected: all tests pass.

**Step 2: Run mypy over the entire project**

```bash
uv run mypy squidbot/
```
Expected: no errors.

**Step 3: Run ruff over the entire project**

```bash
uv run ruff check .
uv run ruff format --check .
```
Expected: no errors, no reformatting needed.

**Step 4: Done**

All four changed files (`models.py`, `memory.py`, `agent.py`, `search_history.py`) are committed. The feature is complete.
