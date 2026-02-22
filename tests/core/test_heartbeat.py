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
