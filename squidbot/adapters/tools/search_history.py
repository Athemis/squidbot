"""
Search history tool — allows the agent to search past conversations.

Reads from the global history.jsonl via JsonlMemory. Only user and assistant
messages are searchable; tool calls and system messages are excluded from both
search and output.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from squidbot.adapters.persistence.jsonl import JsonlMemory
from squidbot.core.models import Message, ToolDefinition, ToolResult


class SearchHistoryTool:
    """
    Search the global history JSONL for a text pattern.

    Returns matching user/assistant messages with ±1 surrounding messages
    for context. Supports filtering by time period (last N days) and
    limiting the number of results.
    """

    name = "search_history"
    description = (
        "Search conversation history across all channels for a text pattern. "
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
        """
        self._base_dir = base_dir

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

        # Load all messages from global history
        all_messages: list[Message] = await JsonlMemory(self._base_dir).load_history()

        # Apply date filter
        if cutoff is not None:
            all_messages = [m for m in all_messages if m.timestamp >= cutoff]

        # Find matches in user/assistant messages only
        matches: list[tuple[Message, int]] = []
        for idx, msg in enumerate(all_messages):
            if msg.role in ("user", "assistant") and msg.content and query in msg.content.lower():
                matches.append((msg, idx))
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
        for i, (msg, idx) in enumerate(matches, 1):
            ts = msg.timestamp.strftime("%Y-%m-%d %H:%M")
            channel = msg.channel or "unknown"
            sender = msg.sender_id or "unknown"
            lines.append(f"## Match {i} — [{channel} / {sender}] | {ts}")
            lines.append("")
            for offset in (-1, 0, 1):
                j = idx + offset
                if 0 <= j < len(all_messages):
                    ctx = all_messages[j]
                    if ctx.role not in ("user", "assistant") or not ctx.content:
                        continue
                    text = ctx.content[:300] + ("..." if len(ctx.content) > 300 else "")
                    role_label = ctx.role.upper()
                    if offset == 0:
                        lines.append(f"**{role_label}: {text}**")
                    else:
                        lines.append(f"{role_label}: {text}")
            lines.append("---")

        return ToolResult(tool_call_id="", content="\n".join(lines), is_error=False)
