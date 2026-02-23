# Gateway memory_write Fix — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Pass `extra_tools=[MemoryWriteTool(storage=storage)]` to `agent_loop.run()` in `_channel_loop_with_state` and `_channel_loop` so Matrix/Email agents can call `memory_write`.

**Architecture:** Both private helper functions receive `storage: JsonlMemory` as a new parameter. Each iteration constructs a fresh `MemoryWriteTool` and passes it via `extra_tools` — identical to the pattern used by CLI chat, cron, and heartbeat call-sites. A `# TODO` comment is added to `_make_agent_loop`'s return type annotation.

**Tech Stack:** Python 3.14, pytest, unittest.mock, ruff, mypy

**Design doc:** `docs/plans/2026-02-23-gateway-memory-write-design.md`

**Prerequisite:** 360 tests pass on `main`. Confirm: `uv run pytest -q`

---

### Task 1: Add `storage` parameter to `_channel_loop_with_state` and wire `extra_tools`

**Files:**
- Modify: `squidbot/cli/main.py:586-628`
- Create: `tests/adapters/test_channel_loops.py`

**Step 1: Write the failing test**

Create `tests/adapters/test_channel_loops.py`:

```python
"""Tests for CLI channel loop helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from squidbot.cli.main import GatewayState, _channel_loop, _channel_loop_with_state
from squidbot.core.models import InboundMessage, Session


def _make_fake_channel(session_id: str = "s1", text: str = "hello") -> MagicMock:
    """Return a channel that yields one InboundMessage then stops."""
    inbound = InboundMessage(
        session=Session(channel="matrix", sender_id="@user:example.com", id=session_id),
        text=text,
    )

    async def _receive():
        yield inbound

    channel = MagicMock()
    channel.receive = _receive
    return channel


async def test_channel_loop_with_state_passes_extra_tools():
    """_channel_loop_with_state must call loop.run with a non-empty extra_tools list."""
    storage = MagicMock()
    loop = MagicMock()
    loop.run = AsyncMock()
    state = GatewayState(active_sessions={}, channel_status=[], cron_jobs_cache=[])
    channel = _make_fake_channel()

    with patch("squidbot.cli.main.MemoryWriteTool") as mock_tool_cls:
        mock_tool_cls.return_value = MagicMock()
        await _channel_loop_with_state(channel, loop, state, storage)

    loop.run.assert_awaited_once()
    _, kwargs = loop.run.call_args
    assert "extra_tools" in kwargs
    assert len(kwargs["extra_tools"]) == 1
    mock_tool_cls.assert_called_once_with(storage=storage)


async def test_channel_loop_passes_extra_tools():
    """_channel_loop must call loop.run with a non-empty extra_tools list."""
    storage = MagicMock()
    loop = MagicMock()
    loop.run = AsyncMock()
    channel = _make_fake_channel()

    with patch("squidbot.cli.main.MemoryWriteTool") as mock_tool_cls:
        mock_tool_cls.return_value = MagicMock()
        await _channel_loop(channel, loop, storage)

    loop.run.assert_awaited_once()
    _, kwargs = loop.run.call_args
    assert "extra_tools" in kwargs
    assert len(kwargs["extra_tools"]) == 1
    mock_tool_cls.assert_called_once_with(storage=storage)
```

**Step 2: Run tests to verify they fail**

```
uv run pytest tests/adapters/test_channel_loops.py -v
```

Expected: both tests FAIL — `_channel_loop_with_state` and `_channel_loop` don't accept `storage` yet.

**Step 3: Update `_channel_loop_with_state` in `squidbot/cli/main.py`**

Replace lines 586–617:

Old:
```python
async def _channel_loop_with_state(
    channel: ChannelPort,
    loop: Any,
    state: GatewayState,
) -> None:
    """
    Drive a single channel and update GatewayState on each message.

    Creates a SessionInfo entry on first message from a session, then increments
    message_count on subsequent messages.

    Args:
        channel: The channel adapter to drive.
        loop: The agent loop to handle each message.
        state: Live gateway state — updated in-place.
    """
    from squidbot.core.models import SessionInfo  # noqa: PLC0415

    async for inbound in channel.receive():
        sid = inbound.session.id
        if sid in state.active_sessions:
            state.active_sessions[sid].message_count += 1
        else:
            state.active_sessions[sid] = SessionInfo(
                session_id=sid,
                channel=inbound.session.channel,
                sender_id=inbound.session.sender_id,
                started_at=datetime.now(),
                message_count=1,
            )
        await loop.run(inbound.session, inbound.text, channel)
```

New:
```python
async def _channel_loop_with_state(
    channel: ChannelPort,
    loop: Any,
    state: GatewayState,
    storage: JsonlMemory,
) -> None:
    """
    Drive a single channel and update GatewayState on each message.

    Creates a SessionInfo entry on first message from a session, then increments
    message_count on subsequent messages.

    Args:
        channel: The channel adapter to drive.
        loop: The agent loop to handle each message.
        state: Live gateway state — updated in-place.
        storage: Persistence adapter used to construct MemoryWriteTool per message.
    """
    from squidbot.adapters.tools.memory_write import MemoryWriteTool  # noqa: PLC0415
    from squidbot.core.models import SessionInfo  # noqa: PLC0415

    async for inbound in channel.receive():
        sid = inbound.session.id
        if sid in state.active_sessions:
            state.active_sessions[sid].message_count += 1
        else:
            state.active_sessions[sid] = SessionInfo(
                session_id=sid,
                channel=inbound.session.channel,
                sender_id=inbound.session.sender_id,
                started_at=datetime.now(),
                message_count=1,
            )
        extra = [MemoryWriteTool(storage=storage)]
        await loop.run(inbound.session, inbound.text, channel, extra_tools=extra)
```

**Step 4: Update `_channel_loop` in `squidbot/cli/main.py`**

Replace lines 619–628:

Old:
```python
async def _channel_loop(channel: ChannelPort, loop: Any) -> None:
    """
    Drive a single channel without state tracking (used by agent command).

    Args:
        channel: The channel adapter to drive.
        loop: The agent loop to handle each message.
    """
    async for inbound in channel.receive():
        await loop.run(inbound.session, inbound.text, channel)
```

New:
```python
async def _channel_loop(channel: ChannelPort, loop: Any, storage: JsonlMemory) -> None:
    """
    Drive a single channel without state tracking (used by agent command).

    Args:
        channel: The channel adapter to drive.
        loop: The agent loop to handle each message.
        storage: Persistence adapter used to construct MemoryWriteTool per message.
    """
    from squidbot.adapters.tools.memory_write import MemoryWriteTool  # noqa: PLC0415

    async for inbound in channel.receive():
        extra = [MemoryWriteTool(storage=storage)]
        await loop.run(inbound.session, inbound.text, channel, extra_tools=extra)
```

**Step 5: Run tests to verify they pass**

```
uv run pytest tests/adapters/test_channel_loops.py -v
```

Expected: both tests PASS.

**Step 6: Commit**

```bash
git add squidbot/cli/main.py tests/adapters/test_channel_loops.py
git commit -m "feat(cli): pass memory_write tool to gateway channel loops"
```

---

### Task 2: Update call-sites in `_run_gateway` and add TODO to `_make_agent_loop`

**Files:**
- Modify: `squidbot/cli/main.py:394-397` (return type comment)
- Modify: `squidbot/cli/main.py:731` (`_channel_loop_with_state` matrix call)
- Modify: `squidbot/cli/main.py:746` (`_channel_loop_with_state` email call)

**Step 1: Add TODO to `_make_agent_loop` return type**

Find line 397:
```python
) -> tuple[AgentLoop, list[McpConnectionProtocol], JsonlMemory]:
```

Replace with:
```python
) -> tuple[AgentLoop, list[McpConnectionProtocol], JsonlMemory]:  # TODO: type storage as MemoryPort throughout main.py once a second persistence implementation exists
```

**Step 2: Update the Matrix call-site**

Find line 731:
```python
                tg.create_task(_channel_loop_with_state(matrix_ch, agent_loop, state))
```

Replace with:
```python
                tg.create_task(_channel_loop_with_state(matrix_ch, agent_loop, state, storage))
```

**Step 3: Update the Email call-site**

Find line 746:
```python
                tg.create_task(_channel_loop_with_state(email_ch, agent_loop, state))
```

Replace with:
```python
                tg.create_task(_channel_loop_with_state(email_ch, agent_loop, state, storage))
```

**Step 4: Run full test suite + lint + type-check**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy squidbot/
```

Expected: all 362 tests pass, no lint or type errors.

**Step 5: Commit**

```bash
git add squidbot/cli/main.py
git commit -m "fix(cli): wire storage into gateway channel loop call-sites"
```
