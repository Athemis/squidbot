"""
Shell command execution tool.

Runs shell commands via asyncio subprocess. When restrict_to_workspace
is True, the working directory is set to the workspace path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from squidbot.core.models import ToolDefinition, ToolResult


class ShellTool:
    """Executes shell commands, optionally scoped to the workspace directory."""

    name = "shell"
    description = (
        "Execute a shell command. Returns stdout and stderr combined. "
        "Use for running scripts, installing packages, or interacting with the system."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 30).",
                "default": 30,
            },
        },
        "required": ["command"],
    }

    def __init__(self, workspace: Path | None, restrict_to_workspace: bool) -> None:
        self._workspace = workspace
        self._restrict = restrict_to_workspace

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    async def execute(self, command: str, timeout: int = 30, **_: object) -> ToolResult:
        """Run the command and return combined stdout/stderr."""
        cwd = str(self._workspace) if self._restrict and self._workspace else None
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode(errors="replace")
            if proc.returncode != 0:
                return ToolResult(
                    tool_call_id="",
                    content=f"Exit code {proc.returncode}:\n{output}",
                    is_error=True,
                )
            return ToolResult(tool_call_id="", content=output)
        except TimeoutError:
            return ToolResult(
                tool_call_id="", content=f"Command timed out after {timeout}s", is_error=True
            )
        except Exception as e:
            return ToolResult(tool_call_id="", content=str(e), is_error=True)
