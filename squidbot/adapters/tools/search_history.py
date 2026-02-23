"""
Search history tool — allows the agent to search past conversations.

Reads JSONL session files directly from the sessions directory.
User, assistant, tool_call, and tool_result messages are searchable.
The low-level role="tool" (OpenAI API format) and system messages are excluded.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from squidbot.adapters.persistence.jsonl import deserialize_message
from squidbot.core.models import Message, ToolDefinition, ToolResult

_SEARCHABLE_ROLES = frozenset({"user", "assistant", "tool_call", "tool_result"})
_ROLE_LABELS: dict[str, str] = {
    "user": "USER",
    "assistant": "ASSISTANT",
    "tool_call": "TOOL CALL",
    "tool_result": "TOOL RESULT",
}


class SearchHistoryTool:
    """
    Search across all session JSONL files for a text pattern.

    Returns matching user/assistant messages with ±1 surrounding messages
    for context. Supports filtering by time period (last N days) and
    limiting the number of results.
    """

    name = "search_history"
    description = (
        "Search conversation history across all sessions for a text pattern. "
        "Returns matching messages with surrounding context. "
        "Use this to recall past conversations, decisions, or facts the user mentioned."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Text to search for (case-insensitive substring match).",
            },
            "days": {
                "type": "integer",
                "description": (
                    "Only search messages from the last N days. 0 or omitted = all time."
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of matches to return (default 10, max 50).",
            },
        },
        "required": ["query"],
    }

    def __init__(self, base_dir: Path) -> None:
        """
        Args:
            base_dir: Root data directory (same as JsonlMemory base_dir).
                      Session files are read from base_dir/sessions/*.jsonl.
        """
        self._sessions_dir = base_dir / "sessions"

    def to_definition(self) -> ToolDefinition:
        """Return the tool's definition for registration in the tool registry."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Search history for the given query.

        Args:
            query: Text to search for (required, case-insensitive).
            days: Restrict search to the last N days (optional, 0 = all time).
            max_results: Maximum matches to return (optional, default 10, max 50).

        Returns:
            ToolResult with Markdown-formatted matches, or error if query missing.
        """
        query_raw = kwargs.get("query")
        if not isinstance(query_raw, str) or not query_raw.strip():
            return ToolResult(tool_call_id="", content="Error: query is required", is_error=True)
        query = query_raw.strip().lower()

        days: int = 0
        if isinstance(kwargs.get("days"), int):
            days = max(0, kwargs["days"])

        max_results: int = 10
        if isinstance(kwargs.get("max_results"), int):
            max_results = min(50, max(1, kwargs["max_results"]))

        cutoff: datetime | None = datetime.now() - timedelta(days=days) if days > 0 else None

        # Load all messages from all session files
        sessions_dir = self._sessions_dir

        def _load_all_messages() -> list[tuple[str, str]]:
            """Return (session_id, line) pairs from all session files."""
            pairs: list[tuple[str, str]] = []
            if not sessions_dir.exists():
                return pairs
            for jsonl_file in sorted(sessions_dir.glob("*.jsonl")):
                session_id = jsonl_file.stem.replace("__", ":")
                for line in jsonl_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        pairs.append((session_id, line))
            return pairs

        raw_pairs = await asyncio.to_thread(_load_all_messages)
        all_messages: list[tuple[str, Message]] = []
        for session_id, line in raw_pairs:
            try:
                msg = deserialize_message(line)
                all_messages.append((session_id, msg))
            except Exception:
                continue

        # Apply date filter
        if cutoff is not None:
            all_messages = [(sid, m) for sid, m in all_messages if m.timestamp >= cutoff]

        # Find matches in searchable messages
        matches: list[tuple[str, Message, int]] = []
        for idx, (session_id, msg) in enumerate(all_messages):
            if msg.role in _SEARCHABLE_ROLES and msg.content and query in msg.content.lower():
                matches.append((session_id, msg, idx))
            if len(matches) >= max_results:
                break

        if not matches:
            return ToolResult(
                tool_call_id="",
                content=f"No matches found for '{query_raw.strip()}'.",
                is_error=False,
            )

        # Format output with context
        lines: list[str] = []
        for i, (session_id, msg, idx) in enumerate(matches, 1):
            ts = msg.timestamp.strftime("%Y-%m-%d %H:%M")
            lines.append(f"## Match {i} — Session: {session_id} | {ts}")
            lines.append("")
            for offset in (-1, 0, 1):
                j = idx + offset
                if 0 <= j < len(all_messages):
                    _, ctx = all_messages[j]
                    if ctx.role not in _SEARCHABLE_ROLES or not ctx.content:
                        continue
                    text = ctx.content[:300] + ("..." if len(ctx.content) > 300 else "")
                    role_label = _ROLE_LABELS.get(ctx.role, ctx.role.upper())
                    if offset == 0:
                        lines.append(f"**{role_label}: {text}**")
                    else:
                        lines.append(f"{role_label}: {text}")
            lines.append("---")

        return ToolResult(tool_call_id="", content="\n".join(lines), is_error=False)
