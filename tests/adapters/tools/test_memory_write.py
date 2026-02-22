"""Tests for MemoryWriteTool."""

from __future__ import annotations

from unittest.mock import AsyncMock

from squidbot.adapters.tools.memory_write import MemoryWriteTool


def _make_tool(session_id: str = "test-session") -> tuple[MemoryWriteTool, AsyncMock]:
    """Return a MemoryWriteTool wired to a mock MemoryPort."""
    storage = AsyncMock()
    storage.save_memory_doc = AsyncMock()
    tool = MemoryWriteTool(storage=storage, session_id=session_id)  # type: ignore[arg-type]
    return tool, storage


class TestMemoryWriteToolMissingArgs:
    async def test_no_content_key_returns_error(self) -> None:
        tool, storage = _make_tool()
        result = await tool.execute()
        assert result.is_error
        assert "content is required" in result.content
        storage.save_memory_doc.assert_not_called()

    async def test_content_none_returns_error(self) -> None:
        tool, storage = _make_tool()
        result = await tool.execute(content=None)
        assert result.is_error
        assert "content is required" in result.content
        storage.save_memory_doc.assert_not_called()


class TestMemoryWriteToolEmptyContent:
    async def test_empty_content_is_allowed(self) -> None:
        """Empty string is a valid 'clear memory' operation."""
        tool, storage = _make_tool()
        result = await tool.execute(content="")
        assert not result.is_error
        storage.save_memory_doc.assert_called_once_with("test-session", "")


class TestMemoryWriteToolWrites:
    async def test_writes_content_to_storage(self) -> None:
        tool, storage = _make_tool()
        result = await tool.execute(content="# Notes\n\nUser likes Python.")
        assert not result.is_error
        assert "Memory updated" in result.content
        storage.save_memory_doc.assert_called_once_with(
            "test-session", "# Notes\n\nUser likes Python."
        )
