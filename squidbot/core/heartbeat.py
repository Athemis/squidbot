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

    Skips blank lines, Markdown headings, HTML comments, empty checkboxes,
    and completed (checked) checkboxes regardless of trailing text.
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
        # Checked checkboxes with text (e.g. "- [x] done") are also non-actionable
        if line.startswith(("- [x]", "* [x]", "- [X]", "* [X]")):
            continue
        return False
    return True
