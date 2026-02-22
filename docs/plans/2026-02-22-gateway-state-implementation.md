# GatewayState & StatusPort — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `SessionInfo` + `ChannelStatus` to `core/models.py`, complete `StatusPort` in
`core/ports.py`, and wire a live `GatewayState` + `GatewayStatusAdapter` into the gateway.

**Architecture:** `SessionInfo` and `ChannelStatus` are pure dataclasses in `core/models.py`.
`GatewayState` and `GatewayStatusAdapter` live in `cli/main.py` (not core — gateway infra).
`_channel_loop()` updates `GatewayState.active_sessions` on each inbound message.

**Design doc:** `docs/plans/2026-02-22-gateway-state-design.md`

---

## Task 1: Add `SessionInfo` + `ChannelStatus` to `core/models.py` (TDD)

**Files:**
- Modify: `squidbot/core/models.py`
- Modify: `tests/core/test_models.py` (create if absent)

**Step 1: Write failing tests**

Check if `tests/core/test_models.py` exists. If not, create it. Add:

```python
"""Tests for core data models."""

from __future__ import annotations

from datetime import datetime

from squidbot.core.models import ChannelStatus, SessionInfo


class TestSessionInfo:
    def test_fields(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0)
        info = SessionInfo(
            session_id="matrix:@alice:example.com",
            channel="matrix",
            sender_id="@alice:example.com",
            started_at=now,
            message_count=3,
        )
        assert info.session_id == "matrix:@alice:example.com"
        assert info.channel == "matrix"
        assert info.sender_id == "@alice:example.com"
        assert info.started_at == now
        assert info.message_count == 3


class TestChannelStatus:
    def test_connected_with_no_error(self) -> None:
        status = ChannelStatus(name="matrix", enabled=True, connected=True)
        assert status.name == "matrix"
        assert status.enabled is True
        assert status.connected is True
        assert status.error is None

    def test_error_field(self) -> None:
        status = ChannelStatus(
            name="email", enabled=True, connected=False, error="timeout"
        )
        assert status.error == "timeout"
        assert status.connected is False
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/core/test_models.py -v
```
Expected: `ImportError` — `SessionInfo` and `ChannelStatus` not defined yet.

**Step 3: Add dataclasses to `models.py`**

Add after the `CronJob` dataclass (end of file):

```python
@dataclass
class SessionInfo:
    """Runtime metadata for a session seen since gateway start."""

    session_id: str
    channel: str
    sender_id: str
    started_at: datetime
    message_count: int


@dataclass
class ChannelStatus:
    """Runtime status of a channel adapter."""

    name: str
    enabled: bool
    connected: bool
    error: str | None = None
```

**Step 4: Run tests**

```bash
uv run pytest tests/core/test_models.py -v
```
Expected: all pass.

**Step 5: Run ruff + mypy**

```bash
uv run ruff check . && uv run mypy squidbot/
```
Expected: no errors.

**Step 6: Commit**

```bash
git add squidbot/core/models.py tests/core/test_models.py
git commit --no-gpg-sign -m "feat: add SessionInfo and ChannelStatus dataclasses to core models"
```

---

## Task 2: Update `StatusPort` in `core/ports.py`

**Files:**
- Modify: `squidbot/core/ports.py`

No new tests needed — `StatusPort` is a Protocol (structural typing, verified by mypy).

**Step 1: Update `StatusPort`**

Replace the existing `StatusPort` class (`ports.py:170–188`) with:

```python
class StatusPort(Protocol):
    """
    Interface for gateway status reporting.

    Provides read-only access to runtime state for dashboards or status commands.
    Implementations hold a GatewayState snapshot updated by running components.
    """

    def get_active_sessions(self) -> list[SessionInfo]:
        """Return metadata for all sessions seen since gateway start."""
        ...

    def get_channel_status(self) -> list[ChannelStatus]:
        """Return runtime status of all configured channels."""
        ...

    def get_cron_jobs(self) -> list[CronJob]:
        """Return the current list of scheduled jobs."""
        ...

    def get_skills(self) -> list[SkillMetadata]:
        """Return all discovered skills with availability info."""
        ...
```

Also update the import block at the top of `ports.py` — add `SessionInfo` and
`ChannelStatus` to the models import:

```python
from squidbot.core.models import (
    ChannelStatus,
    CronJob,
    InboundMessage,
    Message,
    OutboundMessage,
    SessionInfo,
    ToolDefinition,
    ToolResult,
)
```

**Step 2: Run mypy**

```bash
uv run mypy squidbot/
```
Expected: no errors.

**Step 3: Run ruff**

```bash
uv run ruff check .
```
Expected: no errors.

**Step 4: Commit**

```bash
git add squidbot/core/ports.py
git commit --no-gpg-sign -m "feat: update StatusPort with typed returns and get_skills()"
```

---

## Task 3: Add `GatewayState` + `GatewayStatusAdapter` to `cli/main.py` (TDD)

**Files:**
- Modify: `squidbot/cli/main.py`
- Create: `tests/adapters/test_gateway_status.py`

**Step 1: Write failing tests**

Create `tests/adapters/test_gateway_status.py`:

```python
"""Tests for GatewayStatusAdapter."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from squidbot.core.models import ChannelStatus, CronJob, SessionInfo
from squidbot.core.skills import SkillMetadata
from pathlib import Path


class TestGatewayStatusAdapter:
    def _make_state(self) -> object:
        from squidbot.cli.main import GatewayState

        return GatewayState(
            active_sessions={},
            channel_status=[],
            cron_jobs_cache=[],
            started_at=datetime(2026, 1, 1, 12, 0, 0),
        )

    def test_get_active_sessions_empty(self) -> None:
        from squidbot.cli.main import GatewayState, GatewayStatusAdapter

        state = GatewayState(
            active_sessions={},
            channel_status=[],
            cron_jobs_cache=[],
            started_at=datetime(2026, 1, 1),
        )
        adapter = GatewayStatusAdapter(state=state, skills_loader=MagicMock())
        assert adapter.get_active_sessions() == []

    def test_get_active_sessions_returns_values(self) -> None:
        from squidbot.cli.main import GatewayState, GatewayStatusAdapter

        info = SessionInfo(
            session_id="email:user@example.com",
            channel="email",
            sender_id="user@example.com",
            started_at=datetime(2026, 1, 1),
            message_count=2,
        )
        state = GatewayState(
            active_sessions={"email:user@example.com": info},
            channel_status=[],
            cron_jobs_cache=[],
            started_at=datetime(2026, 1, 1),
        )
        adapter = GatewayStatusAdapter(state=state, skills_loader=MagicMock())
        result = adapter.get_active_sessions()
        assert result == [info]

    def test_get_channel_status(self) -> None:
        from squidbot.cli.main import GatewayState, GatewayStatusAdapter

        cs = ChannelStatus(name="matrix", enabled=True, connected=True)
        state = GatewayState(
            active_sessions={},
            channel_status=[cs],
            cron_jobs_cache=[],
            started_at=datetime(2026, 1, 1),
        )
        adapter = GatewayStatusAdapter(state=state, skills_loader=MagicMock())
        assert adapter.get_channel_status() == [cs]

    def test_get_cron_jobs(self) -> None:
        from squidbot.cli.main import GatewayState, GatewayStatusAdapter

        job = CronJob(
            id="j1", name="Daily", message="check", schedule="0 9 * * *",
            channel="cli:local",
        )
        state = GatewayState(
            active_sessions={},
            channel_status=[],
            cron_jobs_cache=[job],
            started_at=datetime(2026, 1, 1),
        )
        adapter = GatewayStatusAdapter(state=state, skills_loader=MagicMock())
        assert adapter.get_cron_jobs() == [job]

    def test_get_skills_delegates_to_loader(self) -> None:
        from squidbot.cli.main import GatewayState, GatewayStatusAdapter

        skill = SkillMetadata(
            name="git",
            description="Git operations",
            location=Path("/skills/git/SKILL.md"),
        )
        loader = MagicMock()
        loader.list_skills.return_value = [skill]
        state = GatewayState(
            active_sessions={},
            channel_status=[],
            cron_jobs_cache=[],
            started_at=datetime(2026, 1, 1),
        )
        adapter = GatewayStatusAdapter(state=state, skills_loader=loader)
        assert adapter.get_skills() == [skill]
        loader.list_skills.assert_called_once()
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/adapters/test_gateway_status.py -v
```
Expected: `ImportError` — `GatewayState` and `GatewayStatusAdapter` not defined yet.

**Step 3: Add `GatewayState` + `GatewayStatusAdapter` to `main.py`**

Add after the existing imports block (before the `app = cyclopts.App(...)` line), keeping the
lazy import style consistent. Place these as module-level classes since they're used in
`_run_gateway()`:

Add at the top of `main.py` after the existing `if TYPE_CHECKING:` block:

```python
from __future__ import annotations  # already present

# add to existing imports at top of file:
from dataclasses import dataclass, field
from datetime import datetime
```

Then add these two classes **before** the `app = cyclopts.App(...)` line:

```python
@dataclass
class GatewayState:
    """
    Live runtime state of the gateway process.

    Updated by _channel_loop() and channel setup. Consumed by GatewayStatusAdapter.
    """

    active_sessions: dict[str, SessionInfo]
    channel_status: list[ChannelStatus]
    cron_jobs_cache: list[CronJob]
    started_at: datetime = field(default_factory=datetime.now)


class GatewayStatusAdapter:
    """
    Implements StatusPort by reading from GatewayState.

    Args:
        state: The live gateway state object.
        skills_loader: SkillsPort implementation for get_skills().
    """

    def __init__(self, state: GatewayState, skills_loader: Any) -> None:
        """Initialize with the given state and skills loader."""
        self._state = state
        self._skills_loader = skills_loader

    def get_active_sessions(self) -> list[SessionInfo]:
        """Return all sessions seen since gateway start."""
        return list(self._state.active_sessions.values())

    def get_channel_status(self) -> list[ChannelStatus]:
        """Return the status of all configured channels."""
        return list(self._state.channel_status)

    def get_cron_jobs(self) -> list[CronJob]:
        """Return the current cron job list from the in-memory cache."""
        return list(self._state.cron_jobs_cache)

    def get_skills(self) -> list[SkillMetadata]:
        """Return all discovered skills via the skills loader."""
        return self._skills_loader.list_skills()
```

Add the necessary imports to the `TYPE_CHECKING` block:

```python
if TYPE_CHECKING:
    from squidbot.adapters.tools.mcp import McpConnectionProtocol
    from squidbot.core.agent import AgentLoop
    from squidbot.core.models import ChannelStatus, CronJob, SessionInfo
    from squidbot.core.ports import ChannelPort
    from squidbot.core.skills import SkillMetadata
```

**Step 4: Run tests**

```bash
uv run pytest tests/adapters/test_gateway_status.py -v
```
Expected: all pass.

**Step 5: Run ruff + mypy**

```bash
uv run ruff check . && uv run mypy squidbot/
```
Expected: no errors.

**Step 6: Commit**

```bash
git add squidbot/cli/main.py tests/adapters/test_gateway_status.py
git commit --no-gpg-sign -m "feat: add GatewayState and GatewayStatusAdapter"
```

---

## Task 4: Wire `GatewayState` into the gateway (TDD)

**Files:**
- Modify: `squidbot/cli/main.py`
- Modify: `tests/adapters/test_gateway_status.py`

**Step 1: Write failing tests**

Add to `tests/adapters/test_gateway_status.py`:

```python
class TestChannelLoopUpdatesState:
    async def test_first_message_creates_session_info(self) -> None:
        from squidbot.cli.main import GatewayState, _channel_loop_with_state

        from squidbot.core.models import InboundMessage, Session

        state = GatewayState(
            active_sessions={},
            channel_status=[],
            cron_jobs_cache=[],
            started_at=datetime(2026, 1, 1),
        )

        session = Session(channel="email", sender_id="user@example.com")
        inbound = InboundMessage(session=session, text="Hello")

        received: list[InboundMessage] = []

        async def fake_agent_run(sess: object, text: str, channel: object) -> None:
            pass

        async def fake_channel_receive():  # type: ignore[return]
            yield inbound

        fake_channel = MagicMock()
        fake_channel.receive = fake_channel_receive

        await _channel_loop_with_state(fake_channel, fake_agent_run, state)  # type: ignore[arg-type]

        assert "email:user@example.com" in state.active_sessions
        info = state.active_sessions["email:user@example.com"]
        assert info.message_count == 1
        assert info.channel == "email"
        assert info.sender_id == "user@example.com"

    async def test_second_message_increments_count(self) -> None:
        from squidbot.cli.main import GatewayState, _channel_loop_with_state

        from squidbot.core.models import InboundMessage, Session

        state = GatewayState(
            active_sessions={},
            channel_status=[],
            cron_jobs_cache=[],
            started_at=datetime(2026, 1, 1),
        )

        session = Session(channel="email", sender_id="user@example.com")
        msg1 = InboundMessage(session=session, text="First")
        msg2 = InboundMessage(session=session, text="Second")

        async def fake_agent_run(sess: object, text: str, channel: object) -> None:
            pass

        async def fake_channel_receive():  # type: ignore[return]
            yield msg1
            yield msg2

        fake_channel = MagicMock()
        fake_channel.receive = fake_channel_receive

        await _channel_loop_with_state(fake_channel, fake_agent_run, state)  # type: ignore[arg-type]

        assert state.active_sessions["email:user@example.com"].message_count == 2
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/adapters/test_gateway_status.py::TestChannelLoopUpdatesState -v
```
Expected: `ImportError` — `_channel_loop_with_state` not defined yet.

**Step 3: Add `_channel_loop_with_state` to `main.py`**

Replace the existing `_channel_loop` function:

```python
async def _channel_loop(channel: ChannelPort, loop: Any) -> None:
    """
    Drive a single channel: receive messages and run the agent for each.

    Args:
        channel: The channel adapter to drive.
        loop: The agent loop to handle each message.
    """
    async for inbound in channel.receive():
        await loop.run(inbound.session, inbound.text, channel)
```

With this pair:

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

**Step 4: Run tests**

```bash
uv run pytest tests/adapters/test_gateway_status.py -v
```
Expected: all pass.

**Step 5: Update `_run_gateway` to use `_channel_loop_with_state`**

In `_run_gateway()`, replace the two `tg.create_task(_channel_loop(...))` calls with
`tg.create_task(_channel_loop_with_state(..., state))`, and add the `GatewayState`
instantiation before the `TaskGroup`:

```python
# After: cron_jobs = await storage.load_cron_jobs()
state = GatewayState(
    active_sessions={},
    channel_status=[],
    cron_jobs_cache=list(cron_jobs),
    started_at=datetime.now(),
)
```

In the `TaskGroup` block, replace:
```python
tg.create_task(_channel_loop(matrix_ch, agent_loop))
```
with:
```python
state.channel_status.append(ChannelStatus(name="matrix", enabled=True, connected=True))
tg.create_task(_channel_loop_with_state(matrix_ch, agent_loop, state))
```

And similarly for email:
```python
state.channel_status.append(ChannelStatus(name="email", enabled=True, connected=True))
tg.create_task(_channel_loop_with_state(email_ch, agent_loop, state))
```

For disabled channels append with `connected=False`:
```python
state.channel_status.append(ChannelStatus(name="matrix", enabled=False, connected=False))
```

Also add `datetime` to the imports at the top of `main.py` (it's already needed for
`GatewayState.started_at`).

Add to `TYPE_CHECKING` block:
```python
from squidbot.core.models import ChannelStatus, CronJob, SessionInfo
```

**Step 6: Run all tests**

```bash
uv run pytest -q
```
Expected: all pass (1 pre-existing matrix failure ignored).

**Step 7: Run ruff + mypy**

```bash
uv run ruff check . && uv run mypy squidbot/
```
Expected: no errors.

**Step 8: Commit**

```bash
git add squidbot/cli/main.py tests/adapters/test_gateway_status.py
git commit --no-gpg-sign -m "feat: wire GatewayState into gateway channel loop"
```

---

## Task 5: Final Verification

**Step 1: Full test suite**

```bash
uv run pytest -q
```
Expected: all pass (1 pre-existing matrix failure only).

**Step 2: Lint + types**

```bash
uv run ruff check . && uv run mypy squidbot/
```
Expected: 0 errors.

**Step 3: Smoke test**

```bash
squidbot status
```
Expected: runs without error, shows `Email: disabled` / `Matrix: disabled`.
