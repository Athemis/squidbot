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

SEARCHABLE_ROLES = ("user", "assistant")
MAX_CONTEXT_CHARS = 300


def _parse_query(kwargs: dict[str, Any]) -> tuple[str, str] | ToolResult:
    query_raw = kwargs.get("query")
    if not isinstance(query_raw, str) or not query_raw.strip():
        return ToolResult(tool_call_id="", content="Error: query is required", is_error=True)

    raw_query = query_raw.strip()
    return raw_query, raw_query.lower()


def _parse_days(kwargs: dict[str, Any]) -> int:
    days_raw = kwargs.get("days")
    if isinstance(days_raw, int):
        return max(0, days_raw)
    return 0


def _parse_max_results(kwargs: dict[str, Any]) -> int:
    max_results_raw = kwargs.get("max_results")
    if isinstance(max_results_raw, int):
        return min(50, max(1, max_results_raw))
    return 10


def _filter_by_cutoff(messages: list[Message], cutoff: datetime | None) -> list[Message]:
    if cutoff is None:
        return messages
    return [message for message in messages if message.timestamp >= cutoff]


def _find_matches(
    messages: list[Message], normalized_query: str, max_results: int
) -> list[tuple[Message, int]]:
    matches: list[tuple[Message, int]] = []
    for index, message in enumerate(messages):
        if (
            message.role in SEARCHABLE_ROLES
            and message.content
            and normalized_query in message.content.lower()
        ):
            matches.append((message, index))

        if len(matches) >= max_results:
            break

    return matches


def _truncate_content(content: str) -> str:
    if len(content) <= MAX_CONTEXT_CHARS:
        return content
    return content[:MAX_CONTEXT_CHARS] + "..."


def _format_matches(messages: list[Message], matches: list[tuple[Message, int]]) -> str:
    lines: list[str] = []
    for match_number, (message, index) in enumerate(matches, 1):
        timestamp = message.timestamp.strftime("%Y-%m-%d %H:%M")
        channel = message.channel or "unknown"
        sender = message.sender_id or "unknown"
        lines.append(f"## Match {match_number} — [{channel} / {sender}] | {timestamp}")
        lines.append("")

        for offset in (-1, 0, 1):
            context_index = index + offset
            if not 0 <= context_index < len(messages):
                continue

            context_message = messages[context_index]
            if context_message.role not in SEARCHABLE_ROLES or not context_message.content:
                continue

            role_label = context_message.role.upper()
            context_text = _truncate_content(context_message.content)
            if offset == 0:
                lines.append(f"**{role_label}: {context_text}**")
                continue

            lines.append(f"{role_label}: {context_text}")

        lines.append("---")

    return "\n".join(lines)


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
        parsed_query = _parse_query(kwargs)
        if isinstance(parsed_query, ToolResult):
            return parsed_query
        raw_query, normalized_query = parsed_query

        days = _parse_days(kwargs)
        max_results = _parse_max_results(kwargs)
        cutoff: datetime | None = datetime.now() - timedelta(days=days) if days > 0 else None

        # Load all messages from global history
        all_messages = _filter_by_cutoff(await JsonlMemory(self._base_dir).load_history(), cutoff)
        matches = _find_matches(all_messages, normalized_query, max_results)

        if not matches:
            return ToolResult(
                tool_call_id="",
                content=f"No matches found for '{raw_query}'.",
                is_error=False,
            )

        return ToolResult(
            tool_call_id="", content=_format_matches(all_messages, matches), is_error=False
        )
