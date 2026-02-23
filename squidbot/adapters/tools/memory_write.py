"""
Memory write tool — allows the agent to update its long-term memory document.
"""

from __future__ import annotations

from typing import Any

from squidbot.core.models import ToolDefinition, ToolResult
from squidbot.core.ports import MemoryPort


class MemoryWriteTool:
    """
    Allows the agent to persist important information to its global memory document.

    The global memory document (MEMORY.md) is injected into every system prompt under
    '## Your Memory', providing cross-session continuity for facts about the user's
    preferences, ongoing projects, and important context.

    This tool REPLACES the entire document. Callers should merge existing content
    with new information before writing.
    """

    name = "memory_write"
    description = (
        "Update your global long-term memory document (MEMORY.md). "
        "This document is visible in every future session under '## Your Memory'. "
        "Use this to persist: user preferences, ongoing projects, key facts. "
        "The content REPLACES the current document — always merge with existing content first. "
        "Keep the document under ~300 words."
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

    def __init__(self, storage: MemoryPort) -> None:
        self._storage = storage

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        content_raw = kwargs.get("content")
        if not isinstance(content_raw, str):
            return ToolResult(tool_call_id="", content="Error: content is required", is_error=True)
        content: str = content_raw
        await self._storage.save_global_memory(content)
        return ToolResult(tool_call_id="", content="Memory updated successfully.")
