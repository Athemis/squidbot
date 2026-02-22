"""Tests for McpToolAdapter and McpServerConnection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from squidbot.adapters.tools.mcp import McpServerConnection, McpToolAdapter
from squidbot.config.schema import McpServerConfig


def _make_mcp_tool(name: str, description: str, input_schema: dict) -> MagicMock:
    """Build a mock mcp.Tool object."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = input_schema
    return tool


class TestMcpToolAdapter:
    def test_name(self):
        session = MagicMock()
        tool = _make_mcp_tool("search", "Search the web", {"type": "object", "properties": {}})
        adapter = McpToolAdapter(session=session, tool=tool)
        assert adapter.name == "search"

    def test_description(self):
        session = MagicMock()
        tool = _make_mcp_tool("search", "Search the web", {"type": "object", "properties": {}})
        adapter = McpToolAdapter(session=session, tool=tool)
        assert adapter.description == "Search the web"

    def test_parameters(self):
        session = MagicMock()
        schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        tool = _make_mcp_tool("search", "Search", schema)
        adapter = McpToolAdapter(session=session, tool=tool)
        assert adapter.parameters == schema

    async def test_execute_returns_tool_result_on_success(self):
        session = AsyncMock()
        call_result = MagicMock()
        call_result.content = [MagicMock(text="result text")]
        call_result.isError = False
        session.call_tool = AsyncMock(return_value=call_result)

        tool = _make_mcp_tool("search", "Search", {"type": "object", "properties": {}})
        adapter = McpToolAdapter(session=session, tool=tool)

        result = await adapter.execute(query="test")
        assert not result.is_error
        assert "result text" in result.content
        session.call_tool.assert_called_once_with("search", arguments={"query": "test"})

    async def test_execute_returns_error_result_on_exception(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=Exception("connection lost"))

        tool = _make_mcp_tool("search", "Search", {"type": "object", "properties": {}})
        adapter = McpToolAdapter(session=session, tool=tool)

        result = await adapter.execute(query="test")
        assert result.is_error
        assert "connection lost" in result.content

    async def test_execute_returns_error_when_server_reports_error(self):
        session = AsyncMock()
        call_result = MagicMock()
        call_result.content = [MagicMock(text="tool failed")]
        call_result.isError = True
        session.call_tool = AsyncMock(return_value=call_result)

        tool = _make_mcp_tool("search", "Search", {"type": "object", "properties": {}})
        adapter = McpToolAdapter(session=session, tool=tool)

        result = await adapter.execute(query="test")
        assert result.is_error
        assert "tool failed" in result.content

    async def test_execute_handles_multiple_content_blocks(self):
        session = AsyncMock()
        call_result = MagicMock()
        call_result.content = [MagicMock(text="part 1"), MagicMock(text="part 2")]
        call_result.isError = False
        session.call_tool = AsyncMock(return_value=call_result)

        tool = _make_mcp_tool("search", "Search", {"type": "object", "properties": {}})
        adapter = McpToolAdapter(session=session, tool=tool)

        result = await adapter.execute()
        assert "part 1" in result.content
        assert "part 2" in result.content


class TestMcpServerConnectionConfig:
    def test_unknown_transport_raises(self):
        """McpServerConnection should raise ValueError for unknown transport."""
        cfg = McpServerConfig(transport="stdio", command="")
        cfg.transport = "ftp"  # type: ignore[assignment]
        conn = McpServerConnection(name="bad", config=cfg)
        with pytest.raises(ValueError, match="Unknown transport"):
            import asyncio

            asyncio.run(conn.connect())

    async def test_connect_stdio_calls_list_tools(self):
        """connect() via stdio calls session.list_tools() and builds adapters."""
        cfg = McpServerConfig(transport="stdio", command="uvx", args=["mcp-server-test"])

        mock_tool = _make_mcp_tool("tool_a", "Tool A", {"type": "object", "properties": {}})
        list_result = MagicMock()
        list_result.tools = [mock_tool]

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=list_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_streams = (AsyncMock(), AsyncMock())

        with (
            patch("squidbot.adapters.tools.mcp.stdio_client") as mock_stdio,
            patch("squidbot.adapters.tools.mcp.ClientSession", return_value=mock_session),
        ):
            mock_stdio.return_value.__aenter__ = AsyncMock(return_value=mock_streams)
            mock_stdio.return_value.__aexit__ = AsyncMock(return_value=False)

            conn = McpServerConnection(name="test", config=cfg)
            tools = await conn.connect()

        assert len(tools) == 1
        assert tools[0].name == "tool_a"

    async def test_connect_returns_empty_on_failure(self):
        """connect() returns [] and logs warning when server fails to start."""
        cfg = McpServerConfig(transport="stdio", command="nonexistent-command")

        with patch("squidbot.adapters.tools.mcp.stdio_client") as mock_stdio:
            mock_stdio.return_value.__aenter__ = AsyncMock(side_effect=Exception("not found"))
            mock_stdio.return_value.__aexit__ = AsyncMock(return_value=False)

            conn = McpServerConnection(name="test", config=cfg)
            tools = await conn.connect()

        assert tools == []

    # TODO: no test for HTTP transport path (requires patching sse_client)


class TestMcpServerConnectionClose:
    async def test_close_connected_instance_clears_state(self):
        """close() calls aclose() and resets _exit_stack and _session to None."""
        cfg = McpServerConfig(transport="stdio", command="uvx")
        conn = McpServerConnection(name="test", config=cfg)

        mock_stack = AsyncMock()
        mock_stack.aclose = AsyncMock()
        conn._exit_stack = mock_stack
        conn._session = MagicMock()  # type: ignore[assignment]

        await conn.close()

        mock_stack.aclose.assert_called_once()
        assert conn._exit_stack is None
        assert conn._session is None

    async def test_close_suppresses_aclose_error_and_clears_state(self):
        """close() logs a warning when aclose() raises but still clears state."""
        cfg = McpServerConfig(transport="stdio", command="uvx")
        conn = McpServerConnection(name="test", config=cfg)

        mock_stack = AsyncMock()
        mock_stack.aclose = AsyncMock(side_effect=Exception("cleanup failed"))
        conn._exit_stack = mock_stack
        conn._session = MagicMock()  # type: ignore[assignment]

        await conn.close()  # must not raise

        assert conn._exit_stack is None
        assert conn._session is None

    async def test_close_on_unconnected_instance_is_safe(self):
        """close() on a fresh (never connected) instance does nothing."""
        cfg = McpServerConfig(transport="stdio", command="uvx")
        conn = McpServerConnection(name="test", config=cfg)

        await conn.close()  # must not raise

        assert conn._exit_stack is None
        assert conn._session is None
