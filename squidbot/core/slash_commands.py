"""Core slash command parsing and dispatch.

This module defines a minimal, channel-agnostic slash command surface handled
before any LLM call. Commands are interpreted deterministically from raw user
text and return structured outcomes for the agent loop.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlashCommandResult:
    """Outcome of parsing/dispatching a slash command."""

    handled: bool
    response_text: str = ""
    reset_requested: bool = False


HELP_TEXT = "Available commands:\n- /help: show this help\n- /new: start a new conversation context"


def handle_slash_command(text: str) -> SlashCommandResult:
    """Parse and handle a slash command from raw user text.

    Args:
        text: Raw user input text.

    Returns:
        SlashCommandResult indicating whether input was handled directly.
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return SlashCommandResult(handled=False)

    cmd = stripped.split(maxsplit=1)[0].lower()
    if cmd == "/help":
        return SlashCommandResult(handled=True, response_text=HELP_TEXT)
    if cmd == "/new":
        return SlashCommandResult(
            handled=True,
            response_text="Started a new conversation context for this session.",
            reset_requested=True,
        )

    return SlashCommandResult(
        handled=True,
        response_text=f"Unknown command: {cmd}. Use /help for available commands.",
    )
