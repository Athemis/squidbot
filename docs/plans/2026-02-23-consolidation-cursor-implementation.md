# Consolidation Cursor + MemoryWriteTool Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent repeated consolidation across restarts by persisting a cursor, and wire `MemoryWriteTool` into every `AgentLoop.run()` call via `extra_tools`.

**Architecture:** A `.meta.json` file per session stores `last_consolidated` (message count). `MemoryManager._consolidate()` only summarizes messages after the cursor, then advances it. `AgentLoop.run()` accepts an `extra_tools` list merged with the registry for that call only.

**Tech Stack:** Python 3.14, pytest, existing squidbot ports/adapters pattern.

---

### Task 1: Add cursor methods to `MemoryPort` and `InMemoryStorage` test doubles

**Files:**
- Modify: `squidbot/core/ports.py`
- Modify: `tests/core/test_memory.py` (InMemoryStorage)
- Modify: `tests/core/test_agent.py` (InMemoryStorage)

**Step 1: Add failing test for new port methods**

In `tests/core/test_memory.py`, after the existing `InMemoryStorage` class, add a test confirming the storage double has cursor methods:

```python
async def test_cursor_default_is_zero(storage):
    cursor = await storage.load_consolidated_cursor("s1")
    assert cursor == 0


async def test_cursor_roundtrip(storage):
    await storage.save_consolidated_cursor("s1", 42)
    assert await storage.load_consolidated_cursor("s1") == 42
```

Run: `uv run pytest tests/core/test_memory.py::test_cursor_default_is_zero -v`
Expected: FAIL — `InMemoryStorage` has no `load_consolidated_cursor`

**Step 2: Add cursor methods to `InMemoryStorage` in both test files**

In `tests/core/test_memory.py`, add to `InMemoryStorage`:

```python
async def load_consolidated_cursor(self, session_id: str) -> int:
    return self._cursors.get(session_id, 0)

async def save_consolidated_cursor(self, session_id: str, cursor: int) -> None:
    self._cursors[session_id] = cursor
```

And add `self._cursors: dict[str, int] = {}` to `__init__`.

Apply the same change to `InMemoryStorage` in `tests/core/test_agent.py`.

**Step 3: Add methods to `MemoryPort` protocol**

In `squidbot/core/ports.py`, add after `save_memory_doc`:

```python
async def load_consolidated_cursor(self, session_id: str) -> int:
    """Return the last consolidated message index for this session (0 if none)."""
    ...

async def save_consolidated_cursor(self, session_id: str, cursor: int) -> None:
    """Persist the consolidation cursor after a successful consolidation."""
    ...
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/core/test_memory.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add squidbot/core/ports.py tests/core/test_memory.py tests/core/test_agent.py
git commit -m "feat(core): add load/save_consolidated_cursor to MemoryPort"
```

---

### Task 2: Implement cursor methods in `JsonlMemory`

**Files:**
- Modify: `squidbot/adapters/persistence/jsonl.py`
- Create: `tests/adapters/persistence/test_jsonl_cursor.py`

**Step 1: Write failing tests**

Create `tests/adapters/persistence/test_jsonl_cursor.py`:

```python
"""Tests for JsonlMemory consolidation cursor persistence."""

from __future__ import annotations

import pytest

from squidbot.adapters.persistence.jsonl import JsonlMemory


async def test_cursor_defaults_to_zero(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    assert await storage.load_consolidated_cursor("sess1") == 0


async def test_cursor_roundtrip(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_consolidated_cursor("sess1", 80)
    assert await storage.load_consolidated_cursor("sess1") == 80


async def test_cursor_isolated_per_session(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_consolidated_cursor("sess1", 10)
    await storage.save_consolidated_cursor("sess2", 20)
    assert await storage.load_consolidated_cursor("sess1") == 10
    assert await storage.load_consolidated_cursor("sess2") == 20


async def test_cursor_file_created_in_sessions_dir(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_consolidated_cursor("sess1", 5)
    meta = tmp_path / "sessions" / "sess1.meta.json"
    assert meta.exists()


async def test_cursor_safe_id_replaces_colons(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_consolidated_cursor("matrix:room123", 3)
    meta = tmp_path / "sessions" / "matrix__room123.meta.json"
    assert meta.exists()
```

Run: `uv run pytest tests/adapters/persistence/test_jsonl_cursor.py -v`
Expected: All FAIL — methods not yet implemented

**Step 2: Add `_meta_file` helper and implement methods in `JsonlMemory`**

In `squidbot/adapters/persistence/jsonl.py`, add helper after `_memory_file`:

```python
def _meta_file(base_dir: Path, session_id: str) -> Path:
    """Return the .meta.json path for a session."""
    safe_id = session_id.replace(":", "__")
    path = base_dir / "sessions" / f"{safe_id}.meta.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
```

Add methods to `JsonlMemory`:

```python
async def load_consolidated_cursor(self, session_id: str) -> int:
    """Return the last_consolidated cursor, or 0 if no meta file exists."""
    path = _meta_file(self._base, session_id)
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    return int(data.get("last_consolidated", 0))

async def save_consolidated_cursor(self, session_id: str, cursor: int) -> None:
    """Atomically write the last_consolidated cursor to .meta.json."""
    path = _meta_file(self._base, session_id)
    path.write_text(json.dumps({"last_consolidated": cursor}), encoding="utf-8")
```

**Step 3: Run tests**

Run: `uv run pytest tests/adapters/persistence/test_jsonl_cursor.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add squidbot/adapters/persistence/jsonl.py tests/adapters/persistence/test_jsonl_cursor.py
git commit -m "feat(adapters): implement consolidation cursor in JsonlMemory"
```

---

### Task 3: Update `MemoryManager._consolidate()` to use cursor

**Files:**
- Modify: `squidbot/core/memory.py`
- Modify: `tests/core/test_memory.py`

**Step 1: Write failing tests for cursor-aware consolidation**

Add to `tests/core/test_memory.py`:

```python
async def test_consolidation_uses_cursor_not_full_history(storage):
    """After cursor=4, only messages[4:-keep_recent] are summarized."""
    llm = ScriptedLLM("Summary: only new messages.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=4,
        keep_recent_ratio=0.25,  # keep_recent = max(1, int(4*0.25)) = 1
        llm=llm,
    )
    # Simulate 4 already-consolidated messages
    for i in range(6):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    await storage.save_consolidated_cursor("s1", 4)

    # Only 6 - 4 = 2 unconsolidated; threshold=4, so no consolidation triggered
    messages = await manager.build_messages("s1", "sys", "new")
    # All 6 history + system + user = 8 (no consolidation)
    assert len(messages) == 8
    doc = await storage.load_session_summary("s1")
    assert doc == ""


async def test_consolidation_cursor_advances_after_consolidation(storage):
    """Cursor is saved after successful consolidation."""
    llm = ScriptedLLM("Summary: advanced.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=4,
        keep_recent_ratio=0.25,  # keep_recent = 1
        llm=llm,
    )
    for i in range(5):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    # cursor=0, len=5, 5-0=5 > 4: consolidation fires
    await manager.build_messages("s1", "sys", "new")
    # cursor should now be 5 - 1 = 4
    cursor = await storage.load_consolidated_cursor("s1")
    assert cursor == 4


async def test_no_consolidation_above_threshold_if_cursor_covers_it(storage):
    """If cursor already covers the history, no LLM call is made."""
    call_count = 0

    class CountingLLM:
        async def chat(self, messages, tools, *, stream=True):
            nonlocal call_count
            call_count += 1
            async def _gen():
                yield "summary"
            return _gen()

    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=4,
        keep_recent_ratio=0.25,
        llm=CountingLLM(),
    )
    for i in range(10):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    # Cursor at 9 (only 1 unconsolidated message, below threshold of 4)
    await storage.save_consolidated_cursor("s1", 9)
    await manager.build_messages("s1", "sys", "new")
    assert call_count == 0
```

Note: these tests reference `load_session_summary` (Feature B method). Since Feature A is
implemented before Feature B, use `load_memory_doc` for now and update in Feature B task.

Adjusted test (Feature A only — uses `load_memory_doc`):

```python
async def test_consolidation_uses_cursor_not_full_history(storage):
    llm = ScriptedLLM("Summary: only new messages.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=4,
        keep_recent_ratio=0.25,
        llm=llm,
    )
    for i in range(6):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    await storage.save_consolidated_cursor("s1", 4)
    messages = await manager.build_messages("s1", "sys", "new")
    assert len(messages) == 8  # no consolidation
    doc = await storage.load_memory_doc("s1")
    assert doc == ""


async def test_consolidation_cursor_advances_after_consolidation(storage):
    llm = ScriptedLLM("Summary: advanced.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=4,
        keep_recent_ratio=0.25,
        llm=llm,
    )
    for i in range(5):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    await manager.build_messages("s1", "sys", "new")
    cursor = await storage.load_consolidated_cursor("s1")
    assert cursor == 4  # 5 - keep_recent(1)


async def test_no_consolidation_above_threshold_if_cursor_covers_it(storage):
    call_count = 0

    class CountingLLM:
        async def chat(self, messages, tools, *, stream=True):
            nonlocal call_count
            call_count += 1
            async def _gen():
                yield "summary"
            return _gen()

    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=4,
        keep_recent_ratio=0.25,
        llm=CountingLLM(),
    )
    for i in range(10):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    await storage.save_consolidated_cursor("s1", 9)
    await manager.build_messages("s1", "sys", "new")
    assert call_count == 0
```

Run: `uv run pytest tests/core/test_memory.py::test_consolidation_uses_cursor_not_full_history -v`
Expected: FAIL

**Step 2: Update `MemoryManager._consolidate()` to use cursor**

In `squidbot/core/memory.py`, replace `_consolidate()`:

```python
async def _consolidate(self, session_id: str, history: list[Message]) -> list[Message]:
    """
    Summarize unconsolidated messages and append to memory.md, returning recent messages.

    Only summarizes messages[cursor:-keep_recent]. Advances cursor after success.

    Args:
        session_id: Unique session identifier.
        history: Full message history.

    Returns:
        Only the recent messages to keep in context.
    """
    cursor = await self._storage.load_consolidated_cursor(session_id)
    recent = history[-self._keep_recent :]
    to_summarize = history[cursor : -self._keep_recent]

    if not to_summarize:
        return recent

    history_text = ""
    for msg in to_summarize:
        if msg.role in ("user", "assistant"):
            history_text += f"{msg.role}: {msg.content}\n"

    if not history_text.strip():
        return recent

    llm = self._llm
    assert llm is not None  # noqa: S101
    prompt = _CONSOLIDATION_PROMPT.format(history=history_text)
    summary_messages = [Message(role="user", content=prompt)]
    try:
        summary_chunks: list[str] = []
        response_stream = await llm.chat(summary_messages, [])
        async for chunk in response_stream:
            if isinstance(chunk, str):
                summary_chunks.append(chunk)
        summary = "".join(summary_chunks).strip()
    except Exception as e:
        from loguru import logger  # noqa: PLC0415
        logger.warning("Consolidation LLM call failed, skipping: {}", e)
        return recent

    if not summary:
        return recent

    existing = await self._storage.load_memory_doc(session_id)
    updated = f"{existing}\n\n{summary}" if existing.strip() else summary
    await self._storage.save_memory_doc(session_id, updated)

    new_cursor = len(history) - self._keep_recent
    await self._storage.save_consolidated_cursor(session_id, new_cursor)

    return recent
```

Also update the trigger in `build_messages()`. Replace:

```python
if len(history) > self._consolidation_threshold and self._llm is not None:
```

with:

```python
cursor = await self._storage.load_consolidated_cursor(session_id)
if len(history) - cursor > self._consolidation_threshold and self._llm is not None:
```

And update the warning trigger. Replace:

```python
if len(history) >= self._consolidation_threshold - 2:
```

with:

```python
if len(history) - cursor >= self._consolidation_threshold - 2:
```

Note: `cursor` is now computed at the top of `build_messages` and reused.

**Step 3: Run all memory tests**

Run: `uv run pytest tests/core/test_memory.py -v`
Expected: All PASS (the existing threshold tests now use cursor=0 which is the default,
so behaviour is unchanged for fresh sessions)

**Step 4: Commit**

```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "feat(core): use consolidation cursor in MemoryManager"
```

---

### Task 4: Add `extra_tools` to `AgentLoop.run()`

**Files:**
- Modify: `squidbot/core/agent.py`
- Modify: `tests/core/test_agent.py`

**Step 1: Write failing test**

Add to `tests/core/test_agent.py`:

```python
async def test_extra_tool_callable_via_run(storage, memory):
    """A tool passed via extra_tools is callable in this run."""
    tool_call = ToolCall(id="tc_1", name="echo", arguments={"text": "via extra"})
    llm = ScriptedLLM([[tool_call], "done"])
    channel = CollectingChannel()

    loop = AgentLoop(
        llm=llm,
        memory=memory,
        registry=ToolRegistry(),  # empty registry — echo not registered
        system_prompt="test",
    )
    await loop.run(SESSION, "go", channel, extra_tools=[EchoTool()])
    assert any("done" in s for s in channel.sent)


async def test_extra_tool_does_not_pollute_registry(storage, memory):
    """extra_tools from one run are not available in the next run."""
    loop = AgentLoop(
        llm=ScriptedLLM(["ok", "ok"]),
        memory=memory,
        registry=ToolRegistry(),
        system_prompt="test",
    )
    channel = CollectingChannel()
    await loop.run(SESSION, "first", channel, extra_tools=[EchoTool()])
    # Second run without extra_tools: registry still empty
    definitions = loop._registry.get_definitions()
    assert not any(d.name == "echo" for d in definitions)
```

Run: `uv run pytest tests/core/test_agent.py::test_extra_tool_callable_via_run -v`
Expected: FAIL — `run()` does not accept `extra_tools`

**Step 2: Update `AgentLoop.run()` signature and dispatch**

In `squidbot/core/agent.py`:

Update `run()` signature:

```python
async def run(
    self,
    session: Session,
    user_message: str,
    channel: ChannelPort,
    *,
    llm: LLMPort | None = None,
    extra_tools: list[Any] | None = None,
) -> None:
```

Add `from typing import Any` if not already present (check existing imports — `Any` may
already be in use indirectly; add `from typing import Any` after the existing imports).

After `_llm = llm if llm is not None else self._llm`, add:

```python
_extra: dict[str, Any] = {t.name: t for t in (extra_tools or [])}
```

Replace:

```python
tool_definitions = self._registry.get_definitions()
```

with:

```python
from squidbot.core.models import ToolDefinition  # noqa: PLC0415
tool_definitions = self._registry.get_definitions() + [
    ToolDefinition(name=t.name, description=t.description, parameters=t.parameters)
    for t in _extra.values()
]
```

Replace the tool dispatch block:

```python
for tc in tool_calls:
    result = await self._registry.execute(tc.name, tool_call_id=tc.id, **tc.arguments)
```

with:

```python
for tc in tool_calls:
    extra_tool = _extra.get(tc.name)
    if extra_tool is not None:
        result = await extra_tool.execute(**tc.arguments)
        result = ToolResult(
            tool_call_id=tc.id,
            content=result.content,
            is_error=result.is_error,
        )
    else:
        result = await self._registry.execute(tc.name, tool_call_id=tc.id, **tc.arguments)
```

Note: `ToolResult` is already imported. Verify the import at the top of `agent.py`.

Also add `ToolPort` to the type hint — update the import in `ports.py` usage:

```python
from squidbot.core.ports import ChannelPort, LLMPort, ToolPort
```

And change the `extra_tools` parameter type to use `ToolPort`:

```python
extra_tools: list[ToolPort] | None = None,
```

**Step 3: Run agent tests**

Run: `uv run pytest tests/core/test_agent.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add squidbot/core/agent.py tests/core/test_agent.py
git commit -m "feat(core): add extra_tools parameter to AgentLoop.run()"
```

---

### Task 5: Wire `MemoryWriteTool` via `extra_tools` in `cli/main.py`

**Files:**
- Modify: `squidbot/cli/main.py`

**Step 1: Find all `agent_loop.run()` call sites**

There are four call sites in `main.py`:
1. `_run_agent` single-shot: `await agent_loop.run(CliChannel.SESSION, message, channel)`
2. `_run_agent` bootstrap: `await agent_loop.run(CliChannel.SESSION, "BOOTSTRAP.md exists...", channel)`
3. `_run_agent` REPL loop: `await agent_loop.run(inbound.session, inbound.text, channel)`
4. `_run_gateway` cron: `await agent_loop.run(session, job.message, ch, ...)`

**Step 2: Add `MemoryWriteTool` import and helper**

`_make_agent_loop` already has access to `storage`. Add after the `agent_loop = AgentLoop(...)` line:

```python
from squidbot.adapters.tools.memory_write import MemoryWriteTool  # noqa: PLC0415
```

`_make_agent_loop` returns `(agent_loop, mcp_connections)`. We also need `storage` at the
call sites. The cleanest approach: return `storage` as a third element, or pass a factory.

Simplest: also return `storage` from `_make_agent_loop`:

Change return type to `tuple[AgentLoop, list[McpConnectionProtocol], JsonlMemory]` and
add `storage` to the return value. Update all callers (`_run_agent`, `_run_gateway`) to
unpack three values.

**Step 3: Update `_run_agent` call sites**

In single-shot mode:

```python
agent_loop, mcp_connections, storage = await _make_agent_loop(settings)
from squidbot.adapters.tools.memory_write import MemoryWriteTool  # noqa: PLC0415
extra = [MemoryWriteTool(storage=storage, session_id=CliChannel.SESSION.id)]
await agent_loop.run(CliChannel.SESSION, message, channel, extra_tools=extra)
```

In bootstrap mode:

```python
session = CliChannel.SESSION
extra = [MemoryWriteTool(storage=storage, session_id=session.id)]
await agent_loop.run(session, "BOOTSTRAP.md exists. Follow it now.", channel, extra_tools=extra)
```

In REPL loop:

```python
async for inbound in channel.receive():
    extra = [MemoryWriteTool(storage=storage, session_id=inbound.session.id)]
    await agent_loop.run(inbound.session, inbound.text, channel, extra_tools=extra)
```

**Step 4: Update `_run_gateway` cron call site**

```python
async def on_cron_due(job: CronJob) -> None:
    channel_prefix = job.channel.split(":")[0]
    ch = channel_registry.get(channel_prefix)
    if ch is None:
        return
    session = Session(
        channel=channel_prefix,
        sender_id=job.channel.split(":", 1)[1],
    )
    from squidbot.adapters.tools.memory_write import MemoryWriteTool  # noqa: PLC0415
    extra = [MemoryWriteTool(storage=storage, session_id=session.id)]
    await agent_loop.run(session, job.message, ch, extra_tools=extra)  # type: ignore[arg-type]
```

Also update `_channel_loop_with_state` loop in gateway and heartbeat if they call `run()`.
Check `HeartbeatService` — it calls `agent_loop.run()` directly. For now the heartbeat
session ID is stable; add `extra_tools` there too in the heartbeat wiring in `_run_gateway`.

**Step 5: Run full test suite + lint**

```bash
uv run pytest -v
uv run ruff check .
uv run mypy squidbot/
```
Expected: All PASS, no lint errors, no type errors

**Step 6: Commit**

```bash
git add squidbot/cli/main.py
git commit -m "feat(cli): wire MemoryWriteTool as extra_tools at all AgentLoop.run() call sites"
```
