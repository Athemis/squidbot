"""
Heartbeat scheduling and content analysis utilities for squidbot.

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

# Bare unchecked checkboxes with no task text — treated as empty placeholders
_EMPTY_CHECKBOX_PATTERNS = {"- [ ]", "* [ ]"}


def _is_heartbeat_empty(content: str | None) -> bool:
    """
    Return True if HEARTBEAT.md has no actionable content.

    Skips blank lines, Markdown headings, HTML comments (single-line only,
    e.g. ``<!-- placeholder -->``), bare empty checkboxes, and completed
    checkboxes (``[x]`` / ``[X]``) regardless of trailing text.

    Args:
        content: The file content, or None if the file was absent.

    Returns:
        True if there is nothing actionable; False if any actionable line exists.
    """
    if not content:
        return True
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith("<!--"):  # single-line HTML comments only
            continue
        if line in _EMPTY_CHECKBOX_PATTERNS:
            continue
        # Checked checkboxes (with or without trailing text) are non-actionable
        if line.startswith(("- [x]", "* [x]", "- [X]", "* [X]")):
            continue
        return False
    return True
