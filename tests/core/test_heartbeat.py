"""Tests for HeartbeatService and helpers."""

from __future__ import annotations

from squidbot.core.heartbeat import LastChannelTracker, _is_heartbeat_empty
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


from squidbot.config.schema import HeartbeatConfig
from datetime import datetime, timezone as tz
from pathlib import Path
from squidbot.core.heartbeat import HeartbeatService


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
    dt = datetime(2026, 2, 22, 3, 0, tzinfo=tz.utc)
    assert svc._is_in_active_hours(now=dt) is True


def test_active_hours_inside_window():
    svc = _make_service(
        HeartbeatConfig(active_hours_start="08:00", active_hours_end="22:00", timezone="UTC")
    )
    dt = datetime(2026, 2, 22, 12, 0, tzinfo=tz.utc)
    assert svc._is_in_active_hours(now=dt) is True


def test_active_hours_before_window():
    svc = _make_service(
        HeartbeatConfig(active_hours_start="08:00", active_hours_end="22:00", timezone="UTC")
    )
    dt = datetime(2026, 2, 22, 7, 59, tzinfo=tz.utc)
    assert svc._is_in_active_hours(now=dt) is False


def test_active_hours_after_window():
    svc = _make_service(
        HeartbeatConfig(active_hours_start="08:00", active_hours_end="22:00", timezone="UTC")
    )
    dt = datetime(2026, 2, 22, 22, 0, tzinfo=tz.utc)
    assert svc._is_in_active_hours(now=dt) is False


def test_active_hours_zero_width_always_skips():
    """start == end is treated as zero-width window — always outside."""
    svc = _make_service(
        HeartbeatConfig(active_hours_start="08:00", active_hours_end="08:00", timezone="UTC")
    )
    dt = datetime(2026, 2, 22, 8, 0, tzinfo=tz.utc)
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
