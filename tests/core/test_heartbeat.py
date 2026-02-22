"""Tests for HeartbeatService and helpers."""

from __future__ import annotations

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


def test_checked_checkbox_uppercase_is_empty():
    assert _is_heartbeat_empty("- [X] done") is True


def test_real_task_is_not_empty():
    assert _is_heartbeat_empty("- [ ] Check urgent emails") is False
