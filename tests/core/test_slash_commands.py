"""Tests for core slash command parsing and dispatch metadata."""

from __future__ import annotations

from squidbot.core.slash_commands import handle_slash_command


def test_slash_status_sets_status_action() -> None:
    result = handle_slash_command("/status")

    assert result.handled is True
    assert result.action == "status"


def test_slash_history_is_informational_action() -> None:
    result = handle_slash_command("/history")

    assert result.handled is True
    assert result.action == "history"
    assert result.is_error is False


def test_slash_remember_requires_text_argument() -> None:
    result = handle_slash_command("/remember   ")

    assert result.handled is True
    assert result.is_error is True
    assert result.response_text == "Usage: /remember <text>"


def test_slash_remember_sets_argument_when_present() -> None:
    result = handle_slash_command("/remember buy milk")

    assert result.handled is True
    assert result.action == "remember"
    assert result.argument == "buy milk"
