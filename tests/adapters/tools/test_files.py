"""Tests for ReadFileTool, WriteFileTool, and ListFilesTool."""

from __future__ import annotations

from pathlib import Path

from squidbot.adapters.tools.files import ListFilesTool, ReadFileTool, WriteFileTool


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


# ── ReadFileTool ──────────────────────────────────────────────────────────────


class TestReadFileToolMissingArgs:
    async def test_no_path_key_returns_error(self, tmp_path: Path) -> None:
        tool = ReadFileTool(workspace=_workspace(tmp_path), restrict_to_workspace=False)
        result = await tool.execute()
        assert result.is_error
        assert "path is required" in result.content

    async def test_path_none_returns_error(self, tmp_path: Path) -> None:
        tool = ReadFileTool(workspace=_workspace(tmp_path), restrict_to_workspace=False)
        result = await tool.execute(path=None)
        assert result.is_error
        assert "path is required" in result.content


class TestReadFileToolReadsFile:
    async def test_reads_existing_file(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        (ws / "hello.txt").write_text("hello world", encoding="utf-8")
        tool = ReadFileTool(workspace=ws, restrict_to_workspace=False)
        result = await tool.execute(path=str(ws / "hello.txt"))
        assert not result.is_error
        assert result.content == "hello world"

    async def test_missing_file_returns_error(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        tool = ReadFileTool(workspace=ws, restrict_to_workspace=False)
        result = await tool.execute(path=str(ws / "nope.txt"))
        assert result.is_error
        assert "does not exist" in result.content

    async def test_path_outside_workspace_blocked(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        tool = ReadFileTool(workspace=ws, restrict_to_workspace=True)
        result = await tool.execute(path=str(tmp_path / "secret.txt"))
        assert result.is_error
        assert "outside workspace" in result.content


# ── WriteFileTool ─────────────────────────────────────────────────────────────


class TestWriteFileToolMissingArgs:
    async def test_no_content_key_returns_error(self, tmp_path: Path) -> None:
        tool = WriteFileTool(workspace=_workspace(tmp_path), restrict_to_workspace=False)
        result = await tool.execute(path="out.txt")
        assert result.is_error
        assert "content is required" in result.content

    async def test_content_none_returns_error(self, tmp_path: Path) -> None:
        tool = WriteFileTool(workspace=_workspace(tmp_path), restrict_to_workspace=False)
        result = await tool.execute(path="out.txt", content=None)
        assert result.is_error
        assert "content is required" in result.content

    async def test_no_path_key_returns_error(self, tmp_path: Path) -> None:
        tool = WriteFileTool(workspace=_workspace(tmp_path), restrict_to_workspace=False)
        result = await tool.execute(content="data")
        assert result.is_error
        assert "path is required" in result.content

    async def test_path_none_returns_error(self, tmp_path: Path) -> None:
        tool = WriteFileTool(workspace=_workspace(tmp_path), restrict_to_workspace=False)
        result = await tool.execute(path=None, content="data")
        assert result.is_error
        assert "path is required" in result.content


class TestWriteFileToolEmptyContent:
    async def test_empty_content_writes_empty_file(self, tmp_path: Path) -> None:
        """Empty string content must be allowed — writing an empty __init__.py is valid."""
        ws = _workspace(tmp_path)
        tool = WriteFileTool(workspace=ws, restrict_to_workspace=False)
        target = ws / "empty.py"
        result = await tool.execute(path=str(target), content="")
        assert not result.is_error
        assert target.exists()
        assert target.read_text(encoding="utf-8") == ""


class TestWriteFileToolWrites:
    async def test_writes_content_to_file(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        tool = WriteFileTool(workspace=ws, restrict_to_workspace=False)
        target = ws / "out.txt"
        result = await tool.execute(path=str(target), content="hello")
        assert not result.is_error
        assert target.read_text(encoding="utf-8") == "hello"

    async def test_creates_parent_directories(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        tool = WriteFileTool(workspace=ws, restrict_to_workspace=False)
        target = ws / "deep" / "dir" / "file.txt"
        result = await tool.execute(path=str(target), content="nested")
        assert not result.is_error
        assert target.read_text(encoding="utf-8") == "nested"

    async def test_path_outside_workspace_blocked(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        tool = WriteFileTool(workspace=ws, restrict_to_workspace=True)
        result = await tool.execute(path=str(tmp_path / "escape.txt"), content="bad")
        assert result.is_error
        assert "outside workspace" in result.content


# ── ListFilesTool ─────────────────────────────────────────────────────────────


class TestListFilesToolNoneArg:
    async def test_path_none_falls_back_to_workspace_root(self, tmp_path: Path) -> None:
        """path=None should degrade to workspace root, not pass 'None' as a path string."""
        ws = _workspace(tmp_path)
        (ws / "file.txt").write_text("", encoding="utf-8")
        tool = ListFilesTool(workspace=ws, restrict_to_workspace=False)
        result = await tool.execute(path=None)
        assert not result.is_error
        assert "file.txt" in result.content


class TestListFilesToolLists:
    async def test_lists_files_and_dirs(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        (ws / "a.txt").write_text("", encoding="utf-8")
        (ws / "subdir").mkdir()
        tool = ListFilesTool(workspace=ws, restrict_to_workspace=False)
        result = await tool.execute(path=str(ws))
        assert not result.is_error
        assert "a.txt" in result.content
        assert "subdir" in result.content

    async def test_empty_directory_returns_empty_marker(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        tool = ListFilesTool(workspace=ws, restrict_to_workspace=False)
        result = await tool.execute(path=str(ws))
        assert not result.is_error
        assert "(empty)" in result.content
