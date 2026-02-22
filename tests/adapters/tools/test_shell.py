"""Tests for ShellTool."""

from __future__ import annotations

from pathlib import Path

from squidbot.adapters.tools.shell import ShellTool


class TestShellToolMissingArgs:
    async def test_no_command_key_returns_error(self, tmp_path: Path) -> None:
        tool = ShellTool(workspace=tmp_path, restrict_to_workspace=False)
        result = await tool.execute()
        assert result.is_error
        assert "command is required" in result.content

    async def test_command_none_returns_error(self, tmp_path: Path) -> None:
        tool = ShellTool(workspace=tmp_path, restrict_to_workspace=False)
        result = await tool.execute(command=None)
        assert result.is_error
        assert "command is required" in result.content


class TestShellToolExecutes:
    async def test_simple_command_returns_output(self, tmp_path: Path) -> None:
        tool = ShellTool(workspace=tmp_path, restrict_to_workspace=False)
        result = await tool.execute(command="echo hello")
        assert not result.is_error
        assert "hello" in result.content

    async def test_nonzero_exit_returns_error(self, tmp_path: Path) -> None:
        tool = ShellTool(workspace=tmp_path, restrict_to_workspace=False)
        result = await tool.execute(command="exit 1")
        assert result.is_error
        assert "Exit code" in result.content

    async def test_invalid_timeout_falls_back_to_default(self, tmp_path: Path) -> None:
        """A non-integer timeout value should not crash — falls back to 30s."""
        tool = ShellTool(workspace=tmp_path, restrict_to_workspace=False)
        result = await tool.execute(command="echo ok", timeout=None)
        assert not result.is_error
        assert "ok" in result.content
