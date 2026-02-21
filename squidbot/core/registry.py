"""
Tool registry for the agent loop.

Adapters register their tools here; the agent loop queries the registry
for available tool definitions and delegates execution to the correct tool.
"""

from __future__ import annotations

from squidbot.core.models import ToolDefinition, ToolResult
from squidbot.core.ports import ToolPort


class ToolRegistry:
    """Maintains a collection of tools and dispatches execution requests."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolPort] = {}

    def register(self, tool: ToolPort) -> None:
        """Register a tool. Raises ValueError on duplicate names."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def get_definitions(self) -> list[ToolDefinition]:
        """Return OpenAI-format tool definitions for all registered tools."""
        return [
            ToolDefinition(
                name=t.name,
                description=t.description,
                parameters=t.parameters,
            )
            for t in self._tools.values()
        ]

    async def execute(self, tool_name: str, tool_call_id: str, **kwargs: object) -> ToolResult:
        """
        Execute a tool by name with the given arguments.

        Args:
            tool_name: Name of the tool to call.
            tool_call_id: The LLM-provided ID for this tool call.
            **kwargs: Tool-specific arguments.

        Returns:
            ToolResult with the output. Returns an error result if the tool
            is not found rather than raising an exception.
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(
                tool_call_id=tool_call_id,
                content=f"Error: unknown tool '{tool_name}'",
                is_error=True,
            )
        result = await tool.execute(**kwargs)
        result.tool_call_id = tool_call_id
        return result
