"""Search tool for the global conversation history.

This tool scans the global ``history.jsonl`` file in one pass (streaming) so it can
work on large histories without loading the full file into memory.

Only user and assistant messages are searchable and shown in output; tool and system
messages are excluded.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from squidbot.adapters.persistence.jsonl import _history_file, deserialize_message_safe
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


def _scan_history(
    base_dir: Path, normalized_query: str, cutoff: datetime | None, max_results: int
) -> list[tuple[Message | None, Message, Message | None]]:
    path = _history_file(base_dir)
    if not path.exists():
        return []

    contexts: list[tuple[Message | None, Message, Message | None]] = []
    previous_message: Message | None = None
    pending_after_index: int | None = None

    with path.open("r", encoding="utf-8", errors="replace") as history_file:
        for raw_line in history_file:
            line = raw_line.strip()
            if not line:
                continue

            message = deserialize_message_safe(line)
            if message is None:
                continue

            if cutoff is not None and message.timestamp < cutoff:
                continue

            if pending_after_index is not None:
                before, hit, _ = contexts[pending_after_index]
                contexts[pending_after_index] = (before, hit, message)
                pending_after_index = None
                if len(contexts) >= max_results:
                    break

            if (
                message.role in SEARCHABLE_ROLES
                and message.content
                and normalized_query in message.content.lower()
            ):
                contexts.append((previous_message, message, None))
                pending_after_index = len(contexts) - 1

            previous_message = message

    return contexts


def _truncate_content(content: str) -> str:
    if len(content) <= MAX_CONTEXT_CHARS:
        return content
    return content[:MAX_CONTEXT_CHARS] + "..."


def _format_matches(matches: list[tuple[Message | None, Message, Message | None]]) -> str:
    lines: list[str] = []
    for match_number, (before, hit, after) in enumerate(matches, 1):
        timestamp = hit.timestamp.strftime("%Y-%m-%d %H:%M")
        channel = hit.channel or "unknown"
        sender = hit.sender_id or "unknown"
        lines.append(f"## Match {match_number} — [{channel} / {sender}] | {timestamp}")
        lines.append("")

        for context_message in (before, hit, after):
            if context_message is None:
                continue
            if context_message.role not in SEARCHABLE_ROLES or not context_message.content:
                continue

            role_label = context_message.role.upper()
            context_text = _truncate_content(context_message.content)
            if context_message is hit:
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

        matches = await asyncio.to_thread(
            _scan_history,
            self._base_dir,
            normalized_query,
            cutoff,
            max_results,
        )

        if not matches:
            return ToolResult(
                tool_call_id="",
                content=f"No matches found for '{raw_query}'.",
                is_error=False,
            )

        return ToolResult(tool_call_id="", content=_format_matches(matches), is_error=False)
