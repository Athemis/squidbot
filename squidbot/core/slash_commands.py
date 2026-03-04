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
    action: str | None = None
    argument: str | None = None
    is_error: bool = False


HELP_TEXT = (
    "Available commands:\n"
    "- /help: show this help\n"
    "- /new: start a new conversation context\n"
    "- /status: show current session status\n"
    "- /model: show last used model for this session\n"
    "- /pool: show active pool\n"
    "- /pool list: list available pools\n"
    "- /pool use <name>: set pool for this session\n"
    "- /pool reset: reset to default pool\n"
    "- /remember <text>: append a memory note"
)


def _split_command_and_argument(stripped: str) -> tuple[str, str]:
    """Return lower-cased command and optional argument string."""
    parts = stripped.split(maxsplit=1)
    cmd = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""
    return cmd, argument


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

    cmd, argument = _split_command_and_argument(stripped)
    if cmd == "/help":
        return SlashCommandResult(handled=True, response_text=HELP_TEXT)
    if cmd == "/new":
        return SlashCommandResult(
            handled=True,
            response_text="Started a new conversation context for this session.",
            reset_requested=True,
        )
    if cmd == "/status":
        return SlashCommandResult(handled=True, action="status")
    if cmd == "/model":
        return SlashCommandResult(handled=True, action="model")
    if cmd == "/pool":
        return SlashCommandResult(handled=True, action="pool", argument=argument)
    if cmd == "/remember":
        if not argument:
            return SlashCommandResult(
                handled=True,
                response_text="Usage: /remember <text>",
                is_error=True,
            )
        return SlashCommandResult(handled=True, action="remember", argument=argument)

    return SlashCommandResult(
        handled=True,
        response_text=f"Unknown command: {cmd}. Use /help for available commands.",
        is_error=True,
    )
