"""
Memory write tool — allows the agent to update its long-term memory document.
"""

from __future__ import annotations

from typing import Any

from squidbot.core.models import ToolDefinition, ToolResult
from squidbot.core.ports import MemoryPort


class MemoryWriteTool:
    """
    Allows the agent to persist important information to its memory document.

    The memory document (memory.md) is injected into every system prompt,
    providing cross-session continuity for facts about the user's preferences,
    ongoing projects, and important context.
    """

    name = "memory_write"
    description = (
        "Update your long-term memory document. Use this to persist important "
        "information that should be available in future conversations: user preferences, "
        "ongoing projects, key facts. The content REPLACES the current memory document."
    )
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The full new content for the memory document (Markdown).",
            },
        },
        "required": ["content"],
    }

    def __init__(self, storage: MemoryPort, session_id: str) -> None:
        self._storage = storage
        self._session_id = session_id

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        content: str = str(kwargs.get("content", ""))
        if not content:
            return ToolResult(tool_call_id="", content="Error: content is required", is_error=True)
        await self._storage.save_memory_doc(self._session_id, content)
        return ToolResult(tool_call_id="", content="Memory updated successfully.")
