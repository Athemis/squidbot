# MCP Tool Adapter — Design Document

**Date:** 2026-02-22
**Status:** Approved

## Goal

Implement an MCP (Model Context Protocol) tool adapter that connects squidbot to external
MCP servers. Each tool exposed by a server becomes a first-class `ToolPort` in the agent's
tool registry, visible to the LLM like any other tool.

## Architecture

New file: `squidbot/adapters/tools/mcp.py`. No core changes — purely adapter-side.

### Classes

**`McpServerConnection`** — manages a single connection to an MCP server. Supports two
transports: stdio (subprocess via `command` + `args`) and HTTP/SSE (remote via `url`).
Called once at gateway start via `connect()`, held open for the process lifetime, closed
at shutdown via `close()`. Returns a list of `McpToolAdapter` instances after connecting.

**`McpToolAdapter`** — implements `ToolPort` structurally (no inheritance). One instance
per tool per server. `name`, `description`, and `parameters` are populated at connect time
by calling `session.list_tools()`. `execute()` delegates to `session.call_tool()`.

### Config Schema

`mcp_servers` in `ToolsConfig` is currently `dict[str, Any]`. Replace with
`dict[str, McpServerConfig]` where `McpServerConfig` is a typed Pydantic model:

```python
class McpServerConfig(BaseModel):
    transport: Literal["stdio", "http"] = "stdio"
    # stdio fields
    command: str = ""
    args: list[str] = []
    env: dict[str, str] | None = None
    cwd: str | None = None
    # http fields
    url: str = ""
```

Example config:

```json
"mcp_servers": {
  "github": {
    "transport": "stdio",
    "command": "uvx",
    "args": ["mcp-server-github"],
    "env": {"GITHUB_TOKEN": "..."}
  },
  "myapi": {
    "transport": "http",
    "url": "http://localhost:8080/mcp"
  }
}
```

### Wiring in `cli/main.py`

`_make_agent_loop()` iterates over `settings.tools.mcp_servers`. For each entry it creates
an `McpServerConnection`, calls `connect()`, and registers all returned `McpToolAdapter`
instances in the `ToolRegistry`. Connection objects are returned from `_make_agent_loop()`
alongside the `AgentLoop` so the caller can close them on shutdown.

Alternatively: `_run_gateway()` and `_run_agent()` manage the connection lifecycle via
async context managers.

### Data Flow

```
gateway start
    │
    ▼
McpServerConnection.connect()
    │  stdio: spawn subprocess, open stdio_client + ClientSession
    │  http:  open SSE connection + ClientSession
    │
    ▼
session.list_tools() → list[mcp.Tool]
    │
    ▼
McpToolAdapter(session, tool) × N → registered in ToolRegistry
    │
    ▼
Agent receives tool call
    │
    ▼
McpToolAdapter.execute(**kwargs)
    │
    ▼
session.call_tool(name, arguments) → ToolResult
```

## Error Handling

- **Connect fails** → loguru `WARNING`, server skipped, no crash. Gateway continues with
  remaining servers.
- **`execute()` raises** → `ToolResult(is_error=True, content="MCP error: ...")`. The LLM
  sees the error as a tool response. Never raises from `execute()`.
- **Mid-session disconnect** → `execute()` catches the exception and returns an error result.
  Reconnect logic is explicitly out of scope (YAGNI).

## Testing

`tests/adapters/tools/test_mcp.py` using `unittest.mock`. The MCP `ClientSession` is mocked
— no real server required. Test cases:

- `McpToolAdapter` exposes correct `name`, `description`, `parameters` from `mcp.Tool`
- `execute()` returns formatted `ToolResult` on success
- `execute()` returns error `ToolResult` on `session.call_tool()` exception
- `McpServerConnection.connect()` with unknown transport raises `ValueError`
- Multiple tools from a single server are all registered

## Files

- **Create:** `squidbot/adapters/tools/mcp.py`
- **Modify:** `squidbot/config/schema.py` — replace `dict[str, Any]` with `dict[str, McpServerConfig]`
- **Modify:** `squidbot/cli/main.py` — wire MCP connections in `_make_agent_loop()` / `_run_gateway()` / `_run_agent()`
- **Create:** `tests/adapters/tools/test_mcp.py`

## Non-Goals

- Reconnect / retry on disconnect
- MCP prompts or resources (tools only)
- Server health monitoring
- Dynamic server registration at runtime
