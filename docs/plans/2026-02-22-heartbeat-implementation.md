# Heartbeat Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `HeartbeatService` to the gateway that wakes the agent periodically, reads `HEARTBEAT.md`, and delivers alerts to the last active channel — silently dropping `HEARTBEAT_OK` responses.

**Architecture:** `HeartbeatService` lives in `squidbot/core/heartbeat.py` (no adapter imports). A `LastChannelTracker` tracks the last active channel/session. The gateway wires everything together in `cli/main.py`. Config is extended in `config/schema.py`.

**Tech Stack:** Python 3.14, asyncio, `zoneinfo` (stdlib), pytest-asyncio, existing `AgentLoop` + `ChannelPort`.

---

### Task 1: `_is_heartbeat_empty()` pure function

**Files:**
- Create: `squidbot/core/heartbeat.py`
- Test: `tests/core/test_heartbeat.py`

**Step 1: Write the failing test**

Create `tests/core/test_heartbeat.py`:

```python
"""Tests for HeartbeatService and helpers."""

from __future__ import annotations

import pytest
from squidbot.core.heartbeat import _is_heartbeat_empty


def test_none_is_empty():
    assert _is_heartbeat_empty(None) is True


def test_empty_string_is_empty():
    assert _is_heartbeat_empty("") is True


def test_blank_lines_only_is_empty():
    assert _is_heartbeat_empty("\n\n  \n") is True


def test_headings_only_is_empty():
    assert _is_heartbeat_empty("# Heartbeat\n\n## Tasks\n") is True


def test_content_is_not_empty():
    assert _is_heartbeat_empty("- Check inbox") is False


def test_heading_plus_content_is_not_empty():
    assert _is_heartbeat_empty("# Checklist\n- Check inbox") is False


def test_html_comment_is_empty():
    assert _is_heartbeat_empty("<!-- placeholder -->") is True


def test_empty_checkbox_is_empty():
    assert _is_heartbeat_empty("- [ ]\n* [ ]") is True


def test_checked_checkbox_is_empty():
    assert _is_heartbeat_empty("- [x] done") is True


def test_real_task_is_not_empty():
    assert _is_heartbeat_empty("- [ ] Check urgent emails") is False
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/core/test_heartbeat.py -v
```

Expected: `ImportError` — `heartbeat` module does not exist yet.

**Step 3: Implement `_is_heartbeat_empty` in `squidbot/core/heartbeat.py`**

```python
"""
Heartbeat service for squidbot gateway.

Provides periodic autonomous agent wake-ups. Every N minutes the agent reads
HEARTBEAT.md from the workspace, checks for outstanding tasks, and delivers
alerts to the last active channel. HEARTBEAT_OK responses are silently dropped.
"""

from __future__ import annotations

HEARTBEAT_OK_TOKEN = "HEARTBEAT_OK"

DEFAULT_HEARTBEAT_PROMPT = (
    "Read HEARTBEAT.md if it exists in your workspace. "
    "Follow any instructions strictly. Do not repeat tasks from prior turns. "
    "If nothing needs attention, reply with just: HEARTBEAT_OK"
)

# Lines considered "empty" for HEARTBEAT.md skip logic
_EMPTY_CHECKBOX_PATTERNS = {"- [ ]", "* [ ]", "- [x]", "* [x]"}


def _is_heartbeat_empty(content: str | None) -> bool:
    """
    Return True if HEARTBEAT.md has no actionable content.

    Skips blank lines, Markdown headings, HTML comments, and empty checkboxes.
    """
    if not content:
        return True
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith("<!--"):
            continue
        if line in _EMPTY_CHECKBOX_PATTERNS:
            continue
        return False
    return True
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/core/test_heartbeat.py -v
```

Expected: all 10 tests PASS.

**Step 5: Commit**

```bash
git add squidbot/core/heartbeat.py tests/core/test_heartbeat.py
git commit -m "feat: add _is_heartbeat_empty helper and heartbeat module skeleton"
```

---

### Task 2: `LastChannelTracker`

**Files:**
- Modify: `squidbot/core/heartbeat.py`
- Test: `tests/core/test_heartbeat.py`

**Step 1: Write the failing tests**

Append to `tests/core/test_heartbeat.py`:

```python
from squidbot.core.heartbeat import LastChannelTracker
from squidbot.core.models import OutboundMessage, Session


class _FakeChannel:
    streaming = False
    sent: list[str]

    def __init__(self) -> None:
        self.sent = []

    async def receive(self):  # type: ignore[override]
        return
        yield  # make it an async generator

    async def send(self, message: OutboundMessage) -> None:
        self.sent.append(message.text)

    async def send_typing(self, session_id: str) -> None:
        pass


def test_tracker_initial_state():
    tracker = LastChannelTracker()
    assert tracker.channel is None
    assert tracker.session is None


def test_tracker_update():
    tracker = LastChannelTracker()
    ch = _FakeChannel()
    session = Session(channel="matrix", sender_id="@alice:example.com")
    tracker.update(ch, session)
    assert tracker.channel is ch
    assert tracker.session is session


def test_tracker_last_update_wins():
    tracker = LastChannelTracker()
    ch1 = _FakeChannel()
    ch2 = _FakeChannel()
    s1 = Session(channel="matrix", sender_id="@alice:example.com")
    s2 = Session(channel="email", sender_id="bob@example.com")
    tracker.update(ch1, s1)
    tracker.update(ch2, s2)
    assert tracker.channel is ch2
    assert tracker.session is s2
```

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/core/test_heartbeat.py::test_tracker_initial_state -v
```

Expected: `ImportError` — `LastChannelTracker` not defined yet.

**Step 3: Implement `LastChannelTracker`**

Append to `squidbot/core/heartbeat.py` (after the existing constants):

```python
from __future__ import annotations  # already at top

from squidbot.core.models import Session
from squidbot.core.ports import ChannelPort


class LastChannelTracker:
    """
    Tracks the most recently active channel and session.

    Updated by the gateway on every inbound message. Read by HeartbeatService
    when determining where to deliver alerts.
    """

    def __init__(self) -> None:
        self.channel: ChannelPort | None = None
        self.session: Session | None = None

    def update(self, channel: ChannelPort, session: Session) -> None:
        """Record the channel and session of the most recent inbound message."""
        self.channel = channel
        self.session = session
```

**Step 4: Run tests**

```bash
uv run pytest tests/core/test_heartbeat.py -v
```

Expected: all tracker tests PASS.

**Step 5: Commit**

```bash
git add squidbot/core/heartbeat.py tests/core/test_heartbeat.py
git commit -m "feat: add LastChannelTracker"
```

---

### Task 3: `HeartbeatConfig` in `config/schema.py`

**Files:**
- Modify: `squidbot/config/schema.py`
- Test: `tests/core/test_heartbeat.py`

**Step 1: Write the failing test**

Append to `tests/core/test_heartbeat.py`:

```python
from squidbot.config.schema import HeartbeatConfig


def test_heartbeat_config_defaults():
    cfg = HeartbeatConfig()
    assert cfg.enabled is True
    assert cfg.interval_minutes == 30
    assert cfg.active_hours_start == "00:00"
    assert cfg.active_hours_end == "24:00"
    assert cfg.timezone == "local"


def test_heartbeat_config_in_agent_config():
    from squidbot.config.schema import AgentConfig
    cfg = AgentConfig()
    assert isinstance(cfg.heartbeat, HeartbeatConfig)
```

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/core/test_heartbeat.py::test_heartbeat_config_defaults -v
```

Expected: `ImportError` — `HeartbeatConfig` not defined yet.

**Step 3: Add `HeartbeatConfig` to `squidbot/config/schema.py`**

After line 35 (`restrict_to_workspace: bool = True`), insert a new class before `AgentConfig` and extend `AgentConfig`:

```python
class HeartbeatConfig(BaseModel):
    """Configuration for the periodic heartbeat service."""

    enabled: bool = True
    interval_minutes: int = 30
    prompt: str = (
        "Read HEARTBEAT.md if it exists in your workspace. "
        "Follow any instructions strictly. Do not repeat tasks from prior turns. "
        "If nothing needs attention, reply with just: HEARTBEAT_OK"
    )
    active_hours_start: str = "00:00"  # HH:MM inclusive
    active_hours_end: str = "24:00"   # HH:MM exclusive; 24:00 = end of day
    timezone: str = "local"           # IANA tz name or "local" (host timezone)
```

Then extend `AgentConfig` to add `heartbeat`:

```python
class AgentConfig(BaseModel):
    """Configuration for agent behavior."""

    workspace: str = str(Path.home() / ".squidbot" / "workspace")
    system_prompt_file: str = "AGENTS.md"
    restrict_to_workspace: bool = True
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
```

**Step 4: Run tests**

```bash
uv run pytest tests/core/test_heartbeat.py -v
```

Expected: all config tests PASS.

**Step 5: Commit**

```bash
git add squidbot/config/schema.py tests/core/test_heartbeat.py
git commit -m "feat: add HeartbeatConfig to schema"
```

---

### Task 4: `HeartbeatService._is_in_active_hours()`

**Files:**
- Modify: `squidbot/core/heartbeat.py`
- Test: `tests/core/test_heartbeat.py`

**Step 1: Write the failing tests**

Append to `tests/core/test_heartbeat.py`:

```python
from datetime import datetime, timezone as tz
from squidbot.core.heartbeat import HeartbeatService
from squidbot.config.schema import HeartbeatConfig


def _make_service(cfg: HeartbeatConfig) -> HeartbeatService:
    """Helper: build a HeartbeatService with stub agent_loop and tracker."""
    return HeartbeatService(
        agent_loop=None,  # type: ignore[arg-type]
        tracker=LastChannelTracker(),
        workspace=Path("/tmp"),
        config=cfg,
    )


def test_active_hours_always_on():
    """Default config (00:00-24:00) is always active."""
    svc = _make_service(HeartbeatConfig(active_hours_start="00:00", active_hours_end="24:00", timezone="UTC"))
    dt = datetime(2026, 2, 22, 3, 0, tzinfo=tz.utc)
    assert svc._is_in_active_hours(now=dt) is True


def test_active_hours_inside_window():
    svc = _make_service(HeartbeatConfig(active_hours_start="08:00", active_hours_end="22:00", timezone="UTC"))
    dt = datetime(2026, 2, 22, 12, 0, tzinfo=tz.utc)
    assert svc._is_in_active_hours(now=dt) is True


def test_active_hours_before_window():
    svc = _make_service(HeartbeatConfig(active_hours_start="08:00", active_hours_end="22:00", timezone="UTC"))
    dt = datetime(2026, 2, 22, 7, 59, tzinfo=tz.utc)
    assert svc._is_in_active_hours(now=dt) is False


def test_active_hours_after_window():
    svc = _make_service(HeartbeatConfig(active_hours_start="08:00", active_hours_end="22:00", timezone="UTC"))
    dt = datetime(2026, 2, 22, 22, 0, tzinfo=tz.utc)
    assert svc._is_in_active_hours(now=dt) is False


def test_active_hours_zero_width_always_skips():
    """start == end is treated as zero-width window — always outside."""
    svc = _make_service(HeartbeatConfig(active_hours_start="08:00", active_hours_end="08:00", timezone="UTC"))
    dt = datetime(2026, 2, 22, 8, 0, tzinfo=tz.utc)
    assert svc._is_in_active_hours(now=dt) is False
```

Also add at the top of the test file: `from pathlib import Path`

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/core/test_heartbeat.py::test_active_hours_always_on -v
```

Expected: `ImportError` or `TypeError` — `HeartbeatService` not defined yet.

**Step 3: Implement `HeartbeatService` skeleton + `_is_in_active_hours`**

Append to `squidbot/core/heartbeat.py`:

```python
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from squidbot.config.schema import HeartbeatConfig
from squidbot.core.agent import AgentLoop

logger = logging.getLogger(__name__)


class HeartbeatService:
    """
    Periodic heartbeat service for the squidbot gateway.

    Wakes the agent every interval_minutes, reads HEARTBEAT.md from the
    workspace, and delivers any alerts to the last active channel.
    HEARTBEAT_OK responses are silently dropped.
    """

    def __init__(
        self,
        agent_loop: AgentLoop,
        tracker: LastChannelTracker,
        workspace: Path,
        config: HeartbeatConfig,
    ) -> None:
        """
        Args:
            agent_loop: The shared agent loop to invoke on each tick.
            tracker: Tracks the last active channel and session.
            workspace: Path to the agent workspace (for HEARTBEAT.md).
            config: Heartbeat configuration.
        """
        self._agent_loop = agent_loop
        self._tracker = tracker
        self._workspace = workspace
        self._config = config

    def _is_in_active_hours(self, now: datetime | None = None) -> bool:
        """Return True if the current time is within the configured active window."""
        if now is None:
            now = datetime.now()

        # Resolve timezone
        tz_name = self._config.timezone
        if tz_name == "local":
            local_now = now.astimezone()
        else:
            try:
                local_now = now.astimezone(ZoneInfo(tz_name))
            except (ZoneInfoNotFoundError, KeyError):
                logger.warning("heartbeat: unknown timezone %r, falling back to local", tz_name)
                local_now = now.astimezone()

        start_h, start_m = (int(x) for x in self._config.active_hours_start.split(":"))
        end_h, end_m = (int(x) for x in self._config.active_hours_end.split(":"))

        # Zero-width window: always outside
        if (start_h, start_m) == (end_h, end_m):
            return False

        current_minutes = local_now.hour * 60 + local_now.minute
        start_minutes = start_h * 60 + start_m
        # 24:00 → 1440 minutes = end of day (exclusive)
        end_minutes = end_h * 60 + end_m if not (end_h == 24 and end_m == 0) else 24 * 60

        return start_minutes <= current_minutes < end_minutes
```

**Step 4: Run tests**

```bash
uv run pytest tests/core/test_heartbeat.py -v
```

Expected: all active hours tests PASS.

**Step 5: Commit**

```bash
git add squidbot/core/heartbeat.py tests/core/test_heartbeat.py
git commit -m "feat: add HeartbeatService skeleton with _is_in_active_hours"
```

---

### Task 5: `HeartbeatService._tick()` — core logic

**Files:**
- Modify: `squidbot/core/heartbeat.py`
- Test: `tests/core/test_heartbeat.py`

**Step 1: Write the failing tests**

Append to `tests/core/test_heartbeat.py`:

```python
import asyncio


class _FakeAgentLoop:
    """Scripted agent loop for heartbeat tests."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[tuple[str, str]] = []  # (session_id, user_message)

    async def run(self, session, user_message: str, channel) -> None:
        self.calls.append((session.id, user_message))
        # Simulate delivering the response to the channel
        from squidbot.core.models import OutboundMessage
        await channel.send(OutboundMessage(session=session, text=self._response))


async def test_tick_skips_when_tracker_empty():
    agent = _FakeAgentLoop("HEARTBEAT_OK")
    tracker = LastChannelTracker()
    svc = HeartbeatService(agent_loop=agent, tracker=tracker, workspace=Path("/tmp"), config=HeartbeatConfig())  # type: ignore[arg-type]
    await svc._tick()
    assert agent.calls == []


async def test_tick_skips_outside_active_hours():
    agent = _FakeAgentLoop("HEARTBEAT_OK")
    tracker = LastChannelTracker()
    ch = _FakeChannel()
    session = Session(channel="cli", sender_id="local")
    tracker.update(ch, session)
    cfg = HeartbeatConfig(active_hours_start="08:00", active_hours_end="09:00", timezone="UTC")
    svc = HeartbeatService(agent_loop=agent, tracker=tracker, workspace=Path("/tmp"), config=cfg)  # type: ignore[arg-type]
    # Use a time outside the window (03:00 UTC)
    dt = datetime(2026, 2, 22, 3, 0, tzinfo=tz.utc)
    await svc._tick(now=dt)
    assert agent.calls == []


async def test_tick_skips_empty_heartbeat_file(tmp_path):
    (tmp_path / "HEARTBEAT.md").write_text("# Checklist\n\n")
    agent = _FakeAgentLoop("HEARTBEAT_OK")
    tracker = LastChannelTracker()
    ch = _FakeChannel()
    session = Session(channel="cli", sender_id="local")
    tracker.update(ch, session)
    svc = HeartbeatService(agent_loop=agent, tracker=tracker, workspace=tmp_path, config=HeartbeatConfig())  # type: ignore[arg-type]
    await svc._tick()
    assert agent.calls == []


async def test_tick_runs_agent_when_file_absent(tmp_path):
    agent = _FakeAgentLoop("HEARTBEAT_OK")
    tracker = LastChannelTracker()
    ch = _FakeChannel()
    session = Session(channel="cli", sender_id="local")
    tracker.update(ch, session)
    svc = HeartbeatService(agent_loop=agent, tracker=tracker, workspace=tmp_path, config=HeartbeatConfig())  # type: ignore[arg-type]
    await svc._tick()
    assert len(agent.calls) == 1


async def test_tick_heartbeat_ok_not_delivered(tmp_path):
    agent = _FakeAgentLoop("HEARTBEAT_OK")
    tracker = LastChannelTracker()
    ch = _FakeChannel()
    session = Session(channel="cli", sender_id="local")
    tracker.update(ch, session)
    svc = HeartbeatService(agent_loop=agent, tracker=tracker, workspace=tmp_path, config=HeartbeatConfig())  # type: ignore[arg-type]
    await svc._tick()
    # HEARTBEAT_OK should be swallowed — the fake channel collects sends
    # but HeartbeatService uses a SinkChannel internally to intercept
    assert ch.sent == []


async def test_tick_alert_delivered(tmp_path):
    (tmp_path / "HEARTBEAT.md").write_text("- Check inbox\n")
    agent = _FakeAgentLoop("You have 3 unread messages.")
    tracker = LastChannelTracker()
    ch = _FakeChannel()
    session = Session(channel="cli", sender_id="local")
    tracker.update(ch, session)
    svc = HeartbeatService(agent_loop=agent, tracker=tracker, workspace=tmp_path, config=HeartbeatConfig())  # type: ignore[arg-type]
    await svc._tick()
    assert ch.sent == ["You have 3 unread messages."]


async def test_tick_heartbeat_ok_at_start_not_delivered(tmp_path):
    agent = _FakeAgentLoop("HEARTBEAT_OK\nSome trailing text")
    tracker = LastChannelTracker()
    ch = _FakeChannel()
    session = Session(channel="cli", sender_id="local")
    tracker.update(ch, session)
    svc = HeartbeatService(agent_loop=agent, tracker=tracker, workspace=tmp_path, config=HeartbeatConfig())  # type: ignore[arg-type]
    await svc._tick()
    assert ch.sent == []


async def test_tick_heartbeat_ok_in_middle_is_delivered(tmp_path):
    agent = _FakeAgentLoop("Some text HEARTBEAT_OK more text")
    tracker = LastChannelTracker()
    ch = _FakeChannel()
    session = Session(channel="cli", sender_id="local")
    tracker.update(ch, session)
    svc = HeartbeatService(agent_loop=agent, tracker=tracker, workspace=tmp_path, config=HeartbeatConfig())  # type: ignore[arg-type]
    await svc._tick()
    assert ch.sent == ["Some text HEARTBEAT_OK more text"]
```

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/core/test_heartbeat.py::test_tick_skips_when_tracker_empty -v
```

Expected: `AttributeError` — `_tick` not defined.

**Step 3: Implement `_tick()` in `HeartbeatService`**

The key design: `_tick()` runs `agent_loop.run()` with a `_SinkChannel` (internal non-streaming channel that captures the response text). After `run()`, the service inspects the text and decides whether to deliver it to `tracker.channel`.

Add `_SinkChannel` (private, module-level) and `_tick()` to `squidbot/core/heartbeat.py`:

```python
import asyncio
from collections.abc import AsyncIterator


class _SinkChannel:
    """Internal channel that captures agent responses without delivering them."""

    streaming = False
    collected: str

    def __init__(self) -> None:
        self.collected = ""

    async def receive(self) -> AsyncIterator[object]:  # type: ignore[override]
        return
        yield  # noqa: unreachable — makes this an async generator

    async def send(self, message: object) -> None:
        from squidbot.core.models import OutboundMessage
        if isinstance(message, OutboundMessage):
            self.collected = message.text

    async def send_typing(self, session_id: str) -> None:
        pass
```

Then add `_tick()` to `HeartbeatService`:

```python
    def _read_heartbeat_file(self) -> str | None:
        """Read HEARTBEAT.md from the workspace, returning None if absent."""
        path = self._workspace / "HEARTBEAT.md"
        try:
            return path.read_text(encoding="utf-8") if path.exists() else None
        except Exception:
            return None

    @staticmethod
    def _is_heartbeat_ok(text: str) -> bool:
        """Return True if response is a HEARTBEAT_OK acknowledgment."""
        stripped = text.strip()
        return (
            stripped == HEARTBEAT_OK_TOKEN
            or stripped.startswith(HEARTBEAT_OK_TOKEN + "\n")
            or stripped.endswith("\n" + HEARTBEAT_OK_TOKEN)
        )

    async def _tick(self, now: datetime | None = None) -> None:
        """Execute a single heartbeat tick."""
        # 1. Need an active session
        if self._tracker.channel is None or self._tracker.session is None:
            logger.debug("heartbeat: skipped (no active session)")
            return

        # 2. Active hours check
        if not self._is_in_active_hours(now=now):
            logger.debug("heartbeat: skipped (outside active hours)")
            return

        # 3. HEARTBEAT.md check
        content = self._read_heartbeat_file()
        if _is_heartbeat_empty(content):
            logger.debug("heartbeat: skipped (HEARTBEAT.md empty)")
            return

        # 4. Run agent into a sink channel
        sink = _SinkChannel()
        try:
            await self._agent_loop.run(self._tracker.session, self._config.prompt, sink)
        except Exception as e:
            logger.error("heartbeat: agent error: %s", e)
            return

        response = sink.collected

        # 5. Deliver or drop
        if self._is_heartbeat_ok(response):
            logger.debug("heartbeat: ok")
            return

        # Real alert — deliver to the last active channel
        from squidbot.core.models import OutboundMessage
        try:
            await self._tracker.channel.send(
                OutboundMessage(session=self._tracker.session, text=response)
            )
        except Exception as e:
            logger.error("heartbeat: delivery error: %s", e)
```

**Step 4: Run tests**

```bash
uv run pytest tests/core/test_heartbeat.py -v
```

Expected: all tests PASS.

**Step 5: Lint and type-check**

```bash
uv run ruff check squidbot/core/heartbeat.py
uv run mypy squidbot/core/heartbeat.py
```

Fix any issues before committing.

**Step 6: Commit**

```bash
git add squidbot/core/heartbeat.py tests/core/test_heartbeat.py
git commit -m "feat: implement HeartbeatService._tick() with HEARTBEAT_OK detection"
```

---

### Task 6: `HeartbeatService.run()` main loop

**Files:**
- Modify: `squidbot/core/heartbeat.py`
- Test: `tests/core/test_heartbeat.py`

**Step 1: Write the failing test**

Append to `tests/core/test_heartbeat.py`:

```python
async def test_run_loop_calls_tick_and_stops(tmp_path):
    """run() should call _tick() at least once and stop when cancelled."""
    tick_count = 0

    class _CountingService(HeartbeatService):
        async def _tick(self, now=None) -> None:
            nonlocal tick_count
            tick_count += 1

    cfg = HeartbeatConfig(interval_minutes=0)  # 0 minutes = fire immediately
    svc = _CountingService(
        agent_loop=None,  # type: ignore[arg-type]
        tracker=LastChannelTracker(),
        workspace=tmp_path,
        config=cfg,
    )

    async def _run_briefly() -> None:
        await asyncio.wait_for(svc.run(), timeout=0.1)

    with pytest.raises((asyncio.TimeoutError, asyncio.CancelledError)):
        await _run_briefly()

    assert tick_count >= 1
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/core/test_heartbeat.py::test_run_loop_calls_tick_and_stops -v
```

Expected: `AttributeError` — `run` not defined.

**Step 3: Implement `run()`**

Add to `HeartbeatService`:

```python
    async def run(self) -> None:
        """
        Start the heartbeat loop.

        Sleeps for interval_minutes between ticks. Runs until cancelled.
        All tick errors are caught internally — this loop never raises.
        """
        if not self._config.enabled:
            logger.info("heartbeat: disabled")
            return

        interval_s = self._config.interval_minutes * 60
        logger.info("heartbeat: started (every %dm)", self._config.interval_minutes)

        while True:
            await asyncio.sleep(interval_s)
            try:
                await self._tick()
            except Exception as e:
                logger.error("heartbeat: unexpected error in tick: %s", e)
```

**Step 4: Run all heartbeat tests**

```bash
uv run pytest tests/core/test_heartbeat.py -v
```

Expected: all tests PASS.

**Step 5: Commit**

```bash
git add squidbot/core/heartbeat.py tests/core/test_heartbeat.py
git commit -m "feat: add HeartbeatService.run() main loop"
```

---

### Task 7: Wire into `_run_gateway()` in `cli/main.py`

**Files:**
- Modify: `squidbot/cli/main.py`

No new tests needed — the wiring is integration-level and covered by the existing unit tests. Verify manually that the gateway starts without error.

**Step 1: Update `_run_gateway()`**

Replace the existing `_run_gateway()` function in `squidbot/cli/main.py` (lines 267–303):

```python
async def _run_gateway(config_path: Path) -> None:
    """Start all enabled channels concurrently."""
    from squidbot.adapters.channels.cli import CliChannel
    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.core.heartbeat import HeartbeatService, LastChannelTracker
    from squidbot.core.models import Session
    from squidbot.core.scheduler import CronScheduler

    settings = Settings.load(config_path)
    agent_loop = await _make_agent_loop(settings)
    storage = JsonlMemory(base_dir=Path.home() / ".squidbot")
    workspace = Path(settings.agents.workspace).expanduser()

    tracker = LastChannelTracker()

    # Map of channel prefix → channel instance for cron job routing
    channel_registry: dict[str, object] = {}
    cli_channel = CliChannel()
    channel_registry["cli"] = cli_channel

    async def run_channel(channel: CliChannel) -> None:
        async for inbound in channel.receive():
            tracker.update(channel, inbound.session)
            await agent_loop.run(inbound.session, inbound.text, channel)

    async def on_cron_due(job) -> None:
        """Deliver a scheduled message to the job's target channel."""
        channel_prefix = job.channel.split(":")[0]
        ch = channel_registry.get(channel_prefix)
        if ch is None:
            return
        session = Session(
            channel=channel_prefix,
            sender_id=job.channel.split(":", 1)[1],
        )
        await agent_loop.run(session, job.message, ch)  # type: ignore[arg-type]

    scheduler = CronScheduler(storage=storage)
    heartbeat = HeartbeatService(
        agent_loop=agent_loop,
        tracker=tracker,
        workspace=workspace,
        config=settings.agents.heartbeat,
    )

    async with asyncio.TaskGroup() as tg:
        tg.create_task(run_channel(cli_channel))
        tg.create_task(scheduler.run(on_due=on_cron_due))
        tg.create_task(heartbeat.run())
```

**Step 2: Lint and type-check**

```bash
uv run ruff check squidbot/cli/main.py
uv run mypy squidbot/cli/main.py
```

**Step 3: Run full test suite**

```bash
uv run pytest -v
```

Expected: all tests PASS.

**Step 4: Commit**

```bash
git add squidbot/cli/main.py
git commit -m "feat: wire HeartbeatService into gateway"
```

---

### Task 8: Final lint, type-check, and full test run

**Step 1: Run everything**

```bash
uv run ruff check .
uv run ruff format .
uv run mypy squidbot/
uv run pytest -v
```

Expected: zero lint errors, zero type errors, all tests PASS.

**Step 2: Commit any format fixes**

```bash
git add -u
git commit -m "chore: ruff format fixes"
```

(Skip this commit if there are no changes.)
