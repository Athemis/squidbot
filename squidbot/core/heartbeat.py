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

# Lines considered "empty" for HEARTBEAT.md skip logic (bare unchecked boxes)
_EMPTY_BARE_CHECKBOXES = {"- [ ]", "* [ ]"}
# Prefixes for completed checkboxes — always non-actionable regardless of text
_DONE_CHECKBOX_PREFIXES = ("- [x]", "* [x]", "- [X]", "* [X]")


def _is_heartbeat_empty(content: str | None) -> bool:
    """
    Return True if HEARTBEAT.md has no actionable content.

    Skips blank lines, Markdown headings, HTML comments, bare empty checkboxes,
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
        if line in _EMPTY_BARE_CHECKBOXES:
            continue
        if line.startswith(_DONE_CHECKBOX_PREFIXES):
            continue
        return False
    return True
