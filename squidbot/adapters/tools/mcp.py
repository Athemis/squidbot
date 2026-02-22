"""
MCP (Model Context Protocol) tool adapter.

Connects squidbot to external MCP servers. Each tool exposed by a server becomes
a first-class ToolPort registered in the agent's ToolRegistry.

Supports two transports:
- stdio: spawns a subprocess (command + args)
- http: connects to a remote SSE endpoint (url)

Connections are established once at startup and held open for the process lifetime.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from mcp import ClientSession
from mcp.client.stdio import stdio_client

from squidbot.config.schema import McpServerConfig
from squidbot.core.models import ToolResult


class McpToolAdapter:
    """
    A single MCP tool exposed as a ToolPort.

    One instance per tool per server. Created by McpServerConnection.connect()
    after listing available tools from the server.
    """

    def __init__(self, session: ClientSession, tool: Any) -> None:
        """
        Args:
            session: The active MCP ClientSession shared with sibling adapters.
            tool: The mcp.Tool object returned by session.list_tools().
        """
        self._session = session
        self.name: str = tool.name
        self.description: str = tool.description or ""
        self.parameters: dict[str, Any] = tool.inputSchema or {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute the MCP tool with the given arguments.

        Args:
            **kwargs: Tool arguments as defined in self.parameters.

        Returns:
            ToolResult with the output or error message. Never raises.
        """
        try:
            result = await self._session.call_tool(self.name, arguments=kwargs)
        except Exception as e:
            return ToolResult(tool_call_id="", content=f"MCP error: {e}", is_error=True)

        # Collect all text content blocks
        text_parts = [block.text for block in result.content if hasattr(block, "text")]
        content = "\n".join(text_parts)

        if result.isError:
            return ToolResult(tool_call_id="", content=content, is_error=True)

        return ToolResult(tool_call_id="", content=content)


class McpServerConnection:
    """
    Manages a persistent connection to a single MCP server.

    Call connect() once at startup to open the connection and retrieve all
    available tools as McpToolAdapter instances. Call close() at shutdown.
    """

    def __init__(self, name: str, config: McpServerConfig) -> None:
        """
        Args:
            name: Human-readable server name (from config key).
            config: Server connection configuration.
        """
        self._name = name
        self._config = config
        self._session: ClientSession | None = None
        self._exit_stack: Any = None

    async def connect(self) -> list[McpToolAdapter]:
        """
        Open the server connection and return all available tools.

        Returns an empty list if the connection fails (with a WARNING log).
        ValueError for unknown transports is re-raised immediately.
        Never raises for other connection failures.

        Returns:
            List of McpToolAdapter instances, one per tool on the server.
        """
        try:
            return await self._connect()
        except ValueError:
            raise
        except Exception as e:
            logger.warning("mcp: server '{}' failed to connect: {}", self._name, e)
            return []

    async def _connect(self) -> list[McpToolAdapter]:
        """Internal connect — raises on failure."""
        from contextlib import AsyncExitStack  # noqa: PLC0415

        stack = AsyncExitStack()
        self._exit_stack = stack

        if self._config.transport == "stdio":
            from mcp.client.stdio import StdioServerParameters  # noqa: PLC0415

            params = StdioServerParameters(
                command=self._config.command,
                args=self._config.args,
                env=self._config.env,
                cwd=self._config.cwd,
            )
            read, write = await stack.enter_async_context(stdio_client(params))

        elif self._config.transport == "http":
            from mcp.client.sse import sse_client  # noqa: PLC0415

            read, write = await stack.enter_async_context(sse_client(self._config.url))

        else:
            raise ValueError(
                f"Unknown transport: {self._config.transport!r}. Use 'stdio' or 'http'."
            )

        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._session = session

        list_result = await session.list_tools()
        tools = [McpToolAdapter(session=session, tool=t) for t in list_result.tools]
        logger.info("mcp: server '{}' connected ({} tools)", self._name, len(tools))
        return tools

    async def close(self) -> None:
        """Close the server connection and clean up resources."""
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception as e:
                logger.warning("mcp: error closing server '{}': {}", self._name, e)
            finally:
                self._exit_stack = None
                self._session = None
