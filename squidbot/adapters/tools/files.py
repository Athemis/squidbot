"""
File operation tools: read, write, and list.

When restrict_to_workspace is True, all paths are resolved relative to
the workspace directory and path traversal outside it is blocked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from squidbot.core.models import ToolDefinition, ToolResult


def _resolve_safe(workspace: Path, path: str, restrict: bool) -> Path | None:
    """
    Resolve a path. Returns None if the path escapes the workspace
    and restriction is enabled.
    """
    p = (workspace / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if restrict and not str(p).startswith(str(workspace.resolve())):
        return None
    return p


class ReadFileTool:
    """Read the contents of a file."""

    name = "read_file"
    description = "Read the contents of a file. Returns the file content as text."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to read."},
        },
        "required": ["path"],
    }

    def __init__(self, workspace: Path, restrict_to_workspace: bool) -> None:
        self._workspace = workspace
        self._restrict = restrict_to_workspace

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name, description=self.description, parameters=self.parameters
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_raw = kwargs.get("path")
        if not isinstance(path_raw, str) or not path_raw:
            return ToolResult(tool_call_id="", content="Error: path is required", is_error=True)
        path: str = path_raw
        resolved = _resolve_safe(self._workspace, path, self._restrict)
        if resolved is None:
            return ToolResult(
                tool_call_id="", content="Error: path is outside workspace", is_error=True
            )
        if not resolved.exists():
            return ToolResult(
                tool_call_id="", content=f"Error: {path} does not exist", is_error=True
            )
        try:
            return ToolResult(tool_call_id="", content=resolved.read_text(encoding="utf-8"))
        except Exception as e:
            return ToolResult(tool_call_id="", content=str(e), is_error=True)


class WriteFileTool:
    """Write content to a file, creating it if it doesn't exist."""

    name = "write_file"
    description = "Write content to a file. Creates parent directories as needed."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to write."},
            "content": {"type": "string", "description": "Content to write."},
        },
        "required": ["path", "content"],
    }

    def __init__(self, workspace: Path, restrict_to_workspace: bool) -> None:
        self._workspace = workspace
        self._restrict = restrict_to_workspace

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name, description=self.description, parameters=self.parameters
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        if "content" not in kwargs:
            return ToolResult(tool_call_id="", content="Error: content is required", is_error=True)
        content_raw = kwargs.get("content")
        if not isinstance(content_raw, str):
            return ToolResult(tool_call_id="", content="Error: content is required", is_error=True)
        content: str = content_raw
        path_raw = kwargs.get("path")
        if not isinstance(path_raw, str) or not path_raw:
            return ToolResult(tool_call_id="", content="Error: path is required", is_error=True)
        path: str = path_raw
        resolved = _resolve_safe(self._workspace, path, self._restrict)
        if resolved is None:
            return ToolResult(
                tool_call_id="", content="Error: path is outside workspace", is_error=True
            )
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return ToolResult(tool_call_id="", content=f"Written {len(content)} bytes to {path}")
        except Exception as e:
            return ToolResult(tool_call_id="", content=str(e), is_error=True)


class ListFilesTool:
    """List files in a directory."""

    name = "list_files"
    description = "List files and directories at the given path."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory to list (default: workspace root).",
                "default": ".",
            },
        },
        "required": [],
    }

    def __init__(self, workspace: Path, restrict_to_workspace: bool) -> None:
        self._workspace = workspace
        self._restrict = restrict_to_workspace

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name, description=self.description, parameters=self.parameters
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_raw = kwargs.get("path", ".")
        path: str = path_raw if isinstance(path_raw, str) else "."
        resolved = _resolve_safe(self._workspace, path, self._restrict)
        if resolved is None:
            return ToolResult(
                tool_call_id="", content="Error: path is outside workspace", is_error=True
            )
        if not resolved.is_dir():
            return ToolResult(
                tool_call_id="", content=f"Error: {path} is not a directory", is_error=True
            )
        entries = sorted(resolved.iterdir(), key=lambda p: (p.is_file(), p.name))
        lines = [f"{'d' if e.is_dir() else 'f'}  {e.name}" for e in entries]
        return ToolResult(tool_call_id="", content="\n".join(lines) if lines else "(empty)")
