"""Tests for HeartbeatService and helpers."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from squidbot.config.schema import HeartbeatConfig
from squidbot.core.heartbeat import HeartbeatService, LastChannelTracker, _is_heartbeat_empty
from squidbot.core.models import OutboundMessage, Session


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


def test_checked_checkbox_uppercase_is_empty():
    assert _is_heartbeat_empty("- [X] done") is True


def test_real_task_is_not_empty():
    assert _is_heartbeat_empty("- [ ] Check urgent emails") is False


class _FakeChannel:
    """Fake channel for testing — collects sent messages."""

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
    svc = _make_service(
        HeartbeatConfig(active_hours_start="00:00", active_hours_end="24:00", timezone="UTC")
    )
    dt = datetime(2026, 2, 22, 3, 0, tzinfo=UTC)
    assert svc._is_in_active_hours(now=dt) is True


def test_active_hours_inside_window():
    svc = _make_service(
        HeartbeatConfig(active_hours_start="08:00", active_hours_end="22:00", timezone="UTC")
    )
    dt = datetime(2026, 2, 22, 12, 0, tzinfo=UTC)
    assert svc._is_in_active_hours(now=dt) is True


def test_active_hours_before_window():
    svc = _make_service(
        HeartbeatConfig(active_hours_start="08:00", active_hours_end="22:00", timezone="UTC")
    )
    dt = datetime(2026, 2, 22, 7, 59, tzinfo=UTC)
    assert svc._is_in_active_hours(now=dt) is False


def test_active_hours_after_window():
    svc = _make_service(
        HeartbeatConfig(active_hours_start="08:00", active_hours_end="22:00", timezone="UTC")
    )
    dt = datetime(2026, 2, 22, 22, 0, tzinfo=UTC)
    assert svc._is_in_active_hours(now=dt) is False


def test_active_hours_zero_width_always_skips():
    """start == end is treated as zero-width window — always outside."""
    svc = _make_service(
        HeartbeatConfig(active_hours_start="08:00", active_hours_end="08:00", timezone="UTC")
    )
    dt = datetime(2026, 2, 22, 8, 0, tzinfo=UTC)
    assert svc._is_in_active_hours(now=dt) is False


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


# ---------------------------------------------------------------------------
# Task 5: HeartbeatService._tick()
# ---------------------------------------------------------------------------


class _FakeAgentLoop:
    """Scripted agent loop for heartbeat tests."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[tuple[str, str]] = []  # (session_id, user_message)

    async def run(self, session: Session, user_message: str, channel: object) -> None:
        self.calls.append((session.id, user_message))
        from squidbot.core.models import OutboundMessage  # noqa: PLC0415

        await channel.send(OutboundMessage(session=session, text=self._response))  # type: ignore[union-attr]


async def test_tick_skips_when_tracker_empty(tmp_path):
    agent = _FakeAgentLoop("HEARTBEAT_OK")
    tracker = LastChannelTracker()
    svc = HeartbeatService(
        agent_loop=agent, tracker=tracker, workspace=tmp_path, config=HeartbeatConfig()
    )  # type: ignore[arg-type]
    await svc._tick()
    assert agent.calls == []


async def test_tick_skips_outside_active_hours(tmp_path):
    agent = _FakeAgentLoop("HEARTBEAT_OK")
    tracker = LastChannelTracker()
    ch = _FakeChannel()
    session = Session(channel="cli", sender_id="local")
    tracker.update(ch, session)  # type: ignore[arg-type]
    cfg = HeartbeatConfig(active_hours_start="08:00", active_hours_end="09:00", timezone="UTC")
    svc = HeartbeatService(agent_loop=agent, tracker=tracker, workspace=tmp_path, config=cfg)  # type: ignore[arg-type]
    dt = datetime(2026, 2, 22, 3, 0, tzinfo=UTC)
    await svc._tick(now=dt)
    assert agent.calls == []


async def test_tick_skips_empty_heartbeat_file(tmp_path):
    (tmp_path / "HEARTBEAT.md").write_text("# Checklist\n\n")
    agent = _FakeAgentLoop("HEARTBEAT_OK")
    tracker = LastChannelTracker()
    ch = _FakeChannel()
    session = Session(channel="cli", sender_id="local")
    tracker.update(ch, session)  # type: ignore[arg-type]
    svc = HeartbeatService(
        agent_loop=agent, tracker=tracker, workspace=tmp_path, config=HeartbeatConfig()
    )  # type: ignore[arg-type]
    await svc._tick()
    assert agent.calls == []


async def test_tick_runs_agent_when_file_absent(tmp_path):
    agent = _FakeAgentLoop("HEARTBEAT_OK")
    tracker = LastChannelTracker()
    ch = _FakeChannel()
    session = Session(channel="cli", sender_id="local")
    tracker.update(ch, session)  # type: ignore[arg-type]
    svc = HeartbeatService(
        agent_loop=agent, tracker=tracker, workspace=tmp_path, config=HeartbeatConfig()
    )  # type: ignore[arg-type]
    await svc._tick()
    assert len(agent.calls) == 1


async def test_tick_heartbeat_ok_not_delivered(tmp_path):
    agent = _FakeAgentLoop("HEARTBEAT_OK")
    tracker = LastChannelTracker()
    ch = _FakeChannel()
    session = Session(channel="cli", sender_id="local")
    tracker.update(ch, session)  # type: ignore[arg-type]
    svc = HeartbeatService(
        agent_loop=agent, tracker=tracker, workspace=tmp_path, config=HeartbeatConfig()
    )  # type: ignore[arg-type]
    await svc._tick()
    assert ch.sent == []


async def test_tick_alert_delivered(tmp_path):
    (tmp_path / "HEARTBEAT.md").write_text("- Check inbox\n")
    agent = _FakeAgentLoop("You have 3 unread messages.")
    tracker = LastChannelTracker()
    ch = _FakeChannel()
    session = Session(channel="cli", sender_id="local")
    tracker.update(ch, session)  # type: ignore[arg-type]
    svc = HeartbeatService(
        agent_loop=agent, tracker=tracker, workspace=tmp_path, config=HeartbeatConfig()
    )  # type: ignore[arg-type]
    await svc._tick()
    assert ch.sent == ["You have 3 unread messages."]


async def test_tick_heartbeat_ok_at_start_not_delivered(tmp_path):
    agent = _FakeAgentLoop("HEARTBEAT_OK\nSome trailing text")
    tracker = LastChannelTracker()
    ch = _FakeChannel()
    session = Session(channel="cli", sender_id="local")
    tracker.update(ch, session)  # type: ignore[arg-type]
    svc = HeartbeatService(
        agent_loop=agent, tracker=tracker, workspace=tmp_path, config=HeartbeatConfig()
    )  # type: ignore[arg-type]
    await svc._tick()
    assert ch.sent == []


async def test_tick_heartbeat_ok_in_middle_is_delivered(tmp_path):
    agent = _FakeAgentLoop("Some text HEARTBEAT_OK more text")
    tracker = LastChannelTracker()
    ch = _FakeChannel()
    session = Session(channel="cli", sender_id="local")
    tracker.update(ch, session)  # type: ignore[arg-type]
    svc = HeartbeatService(
        agent_loop=agent, tracker=tracker, workspace=tmp_path, config=HeartbeatConfig()
    )  # type: ignore[arg-type]
    await svc._tick()
    assert ch.sent == ["Some text HEARTBEAT_OK more text"]


# ---------------------------------------------------------------------------
# Task 6: HeartbeatService.run()
# ---------------------------------------------------------------------------


async def test_run_loop_calls_tick_and_stops(tmp_path):
    """run() should call _tick() at least once and stop when cancelled."""
    tick_count = 0

    class _CountingService(HeartbeatService):
        async def _tick(self, now: datetime | None = None) -> None:
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
