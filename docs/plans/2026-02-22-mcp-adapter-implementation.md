# MCP Tool Adapter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement `McpServerConnection` and `McpToolAdapter` in `adapters/tools/mcp.py` so the agent can use tools from any MCP server (stdio or HTTP/SSE) configured in `mcp_servers`.

**Architecture:** `McpServerConnection` manages a single persistent connection (stdio or HTTP/SSE) and returns a list of `McpToolAdapter` instances — one per tool. Each `McpToolAdapter` implements `ToolPort` structurally and is registered in `ToolRegistry`. Connections are opened at agent-loop construction time and closed on shutdown. No core changes.

**Tech Stack:** Python 3.14, `mcp>=1.26` (`ClientSession`, `stdio_client`, `sse_client`), `httpx`, `unittest.mock`, pytest-asyncio.

---

## Task 1: Add `McpServerConfig` to `config/schema.py`

**Files:**
- Modify: `squidbot/config/schema.py`

**Step 1: Write the failing test**

Append to `tests/core/test_config.py`:

```python
def test_mcp_server_config_stdio_defaults():
    from squidbot.config.schema import McpServerConfig
    cfg = McpServerConfig(command="uvx", args=["mcp-server-github"])
    assert cfg.transport == "stdio"
    assert cfg.command == "uvx"
    assert cfg.args == ["mcp-server-github"]
    assert cfg.env is None
    assert cfg.url == ""


def test_mcp_server_config_http():
    from squidbot.config.schema import McpServerConfig
    cfg = McpServerConfig(transport="http", url="http://localhost:8080/mcp")
    assert cfg.transport == "http"
    assert cfg.url == "http://localhost:8080/mcp"


def test_tools_config_mcp_servers_typed():
    from squidbot.config.schema import McpServerConfig, ToolsConfig
    cfg = ToolsConfig(
        mcp_servers={"github": {"command": "uvx", "args": ["mcp-server-github"]}}
    )
    assert isinstance(cfg.mcp_servers["github"], McpServerConfig)
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/core/test_config.py::test_mcp_server_config_stdio_defaults -v
```

Expected: `ImportError` — `McpServerConfig` not defined yet.

**Step 3: Add `McpServerConfig` and update `ToolsConfig`**

In `squidbot/config/schema.py`, add this class before `ToolsConfig`:

```python
class McpServerConfig(BaseModel):
    """Configuration for a single MCP server connection."""

    transport: Literal["stdio", "http"] = "stdio"
    # stdio transport
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None
    # http transport
    url: str = ""
```

Add `from typing import Literal` to the imports at the top (or add `Literal` to the existing `from typing import Any` line).

Then replace the `mcp_servers` field in `ToolsConfig`:

```python
# Before:
mcp_servers: dict[str, Any] = Field(default_factory=dict)

# After:
mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)
```

**Step 4: Run all config tests**

```bash
uv run pytest tests/core/test_config.py -v
```

Expected: All PASS.

**Step 5: Run full suite + ruff**

```bash
uv run pytest -q && uv run ruff check squidbot/config/schema.py
```

Expected: All pass, no lint errors.

**Step 6: Commit**

```bash
git add squidbot/config/schema.py tests/core/test_config.py
git commit -m "feat: add McpServerConfig to schema"
```

---

## Task 2: Write failing tests for `McpToolAdapter`

**Files:**
- Create: `tests/adapters/tools/test_mcp.py`

**Step 1: Create the test file**

Create `tests/adapters/tools/test_mcp.py`:

```python
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
        schema = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
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
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/adapters/tools/test_mcp.py -v
```

Expected: `ImportError` — `McpToolAdapter` not defined yet.

**Step 3: Commit**

```bash
git add tests/adapters/tools/test_mcp.py
git commit -m "test: add failing tests for McpToolAdapter and McpServerConnection"
```

---

## Task 3: Implement `McpToolAdapter` and `McpServerConnection`

**Files:**
- Create: `squidbot/adapters/tools/mcp.py`

**Step 1: Create the file**

Create `squidbot/adapters/tools/mcp.py`:

```python
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
        Never raises.

        Returns:
            List of McpToolAdapter instances, one per tool on the server.
        """
        try:
            return await self._connect()
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
            raise ValueError(f"Unknown transport: {self._config.transport!r}. Use 'stdio' or 'http'.")

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
```

**Step 2: Run the new tests**

```bash
uv run pytest tests/adapters/tools/test_mcp.py -v
```

Expected: All tests PASS.

**Step 3: Run full suite + ruff**

```bash
uv run pytest -q && uv run ruff check squidbot/adapters/tools/mcp.py
```

Expected: All pass, no lint errors.

**Step 4: Commit**

```bash
git add squidbot/adapters/tools/mcp.py
git commit -m "feat: add McpToolAdapter and McpServerConnection"
```

---

## Task 4: Wire MCP servers into `_make_agent_loop()` and manage lifecycle

**Files:**
- Modify: `squidbot/cli/main.py`

**Step 1: Update `_make_agent_loop()` return type and MCP wiring**

`_make_agent_loop()` currently returns just an `AgentLoop`. Change it to also return the
list of `McpServerConnection` objects so callers can close them on shutdown.

Replace the current `_make_agent_loop` function (lines 246–301) with:

```python
async def _make_agent_loop(
    settings: Settings,
) -> tuple[AgentLoop, list[object]]:
    """
    Construct the agent loop from configuration.

    Returns:
        Tuple of (agent_loop, mcp_connections). Callers must close mcp_connections
        on shutdown by calling conn.close() on each.
    """
    from squidbot.adapters.llm.openai import OpenAIAdapter  # noqa: PLC0415
    from squidbot.adapters.persistence.jsonl import JsonlMemory  # noqa: PLC0415
    from squidbot.adapters.skills.fs import FsSkillsLoader  # noqa: PLC0415
    from squidbot.adapters.tools.files import ListFilesTool, ReadFileTool, WriteFileTool  # noqa: PLC0415
    from squidbot.adapters.tools.shell import ShellTool  # noqa: PLC0415
    from squidbot.core.agent import AgentLoop  # noqa: PLC0415
    from squidbot.core.memory import MemoryManager  # noqa: PLC0415
    from squidbot.core.registry import ToolRegistry  # noqa: PLC0415

    # Resolve workspace path
    workspace = Path(settings.agents.workspace).expanduser()
    workspace.mkdir(parents=True, exist_ok=True)

    # Build storage directory
    storage_dir = Path.home() / ".squidbot"
    storage = JsonlMemory(base_dir=storage_dir)

    # Skills loader (extra dirs → workspace/skills → bundled)
    bundled_skills = Path(__file__).parent.parent / "skills"
    extra_dirs = [Path(d).expanduser() for d in settings.skills.extra_dirs]
    skills = FsSkillsLoader(search_dirs=extra_dirs + [workspace / "skills", bundled_skills])

    memory = MemoryManager(storage=storage, max_history_messages=200, skills=skills)

    # LLM adapter
    llm = OpenAIAdapter(
        api_base=settings.llm.api_base,
        api_key=settings.llm.api_key,
        model=settings.llm.model,
    )

    # Tool registry
    registry = ToolRegistry()
    restrict = settings.agents.restrict_to_workspace

    if settings.tools.shell.enabled:
        registry.register(ShellTool(workspace=workspace, restrict_to_workspace=restrict))
    registry.register(ReadFileTool(workspace=workspace, restrict_to_workspace=restrict))
    registry.register(WriteFileTool(workspace=workspace, restrict_to_workspace=restrict))
    registry.register(ListFilesTool(workspace=workspace, restrict_to_workspace=restrict))

    if settings.tools.web_search.enabled:
        from squidbot.adapters.tools.web_search import WebSearchTool  # noqa: PLC0415

        registry.register(WebSearchTool(config=settings.tools.web_search))

    # MCP servers
    mcp_connections: list[object] = []
    if settings.tools.mcp_servers:
        from squidbot.adapters.tools.mcp import McpServerConnection  # noqa: PLC0415

        for server_name, server_cfg in settings.tools.mcp_servers.items():
            conn = McpServerConnection(name=server_name, config=server_cfg)
            tools = await conn.connect()
            for tool in tools:
                registry.register(tool)
            mcp_connections.append(conn)

    # Load system prompt
    system_prompt_path = workspace / settings.agents.system_prompt_file
    if system_prompt_path.exists():
        system_prompt = system_prompt_path.read_text(encoding="utf-8")
    else:
        system_prompt = "You are a helpful personal AI assistant."

    agent_loop = AgentLoop(llm=llm, memory=memory, registry=registry, system_prompt=system_prompt)
    return agent_loop, mcp_connections
```

**Step 2: Update `_run_agent()` to handle new return type**

In `_run_agent()`, replace:

```python
agent_loop = await _make_agent_loop(settings)
```

With:

```python
agent_loop, mcp_connections = await _make_agent_loop(settings)
```

And add cleanup after the main logic (before the function ends), after the interactive loop
or single-shot mode:

For single-shot mode, add after `print()`:
```python
for conn in mcp_connections:
    await conn.close()  # type: ignore[union-attr]
return
```

For interactive mode, add after the `async for` loop:
```python
for conn in mcp_connections:
    await conn.close()  # type: ignore[union-attr]
```

**Step 3: Update `_run_gateway()` to handle new return type**

In `_run_gateway()`, replace:

```python
agent_loop = await _make_agent_loop(settings)
```

With:

```python
agent_loop, mcp_connections = await _make_agent_loop(settings)
```

Add MCP shutdown after the `TaskGroup` block. The full tail of `_run_gateway()` should end with:

```python
    async with asyncio.TaskGroup() as tg:
        tg.create_task(scheduler.run(on_due=on_cron_due))
        tg.create_task(heartbeat.run())

    for conn in mcp_connections:
        await conn.close()  # type: ignore[union-attr]
```

**Step 4: Run ruff + full suite**

```bash
uv run ruff check squidbot/cli/main.py && uv run pytest -q
```

Expected: No lint errors, all tests pass.

**Step 5: Commit**

```bash
git add squidbot/cli/main.py
git commit -m "feat: wire MCP servers into agent loop"
```

---

## Task 5: mypy type-check + smoke test

**Step 1: Type-check**

```bash
uv run mypy squidbot/
```

Fix any errors that appear. Common expected issues:
- `conn.close()` on `object` type — add `# type: ignore[union-attr]` where needed
  (already included in the plan above)

**Step 2: Reinstall and smoke test**

```bash
uv tool install --reinstall /home/alex/git/squidbot
squidbot --help
```

Expected: No errors.

**Step 3: Final full run**

```bash
uv run ruff check . && uv run pytest -q
```

Expected: All clean.

**Step 4: Commit any fixes**

```bash
git add -u
git commit -m "chore: mypy fixes for MCP adapter wiring"
```

(Skip if no changes needed.)
