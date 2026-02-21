# squidbot — Design Document

**Date:** 2026-02-21  
**Status:** Approved

## Motivation

squidbot is a lightweight personal AI assistant built from scratch. It is inspired by OpenClaw
and nanobot, but not based on either. The goal is an elegant, performant, well-documented
codebase that is fully owned — no upstream drift, no inherited architectural debt.

Key problems with existing forks (nanobot-redux baseline):
- Architectural boundaries not enforced by the language
- Poor testability without external services
- Upstream drift problem when forking
- Accumulated technical debt from rapid upstream development

## Architecture: Hexagonal (Ports & Adapters)

The core principle: the inner domain (agent logic, memory, scheduling) has zero knowledge of
external services. All external dependencies are accessed through explicitly defined `Protocol`
interfaces ("Ports"). Concrete implementations ("Adapters") plug into these ports.

Dependency direction: Adapters → Ports ← Core. The core never imports from adapters.

```
┌─────────────────────────────────────────────┐
│                    CORE                     │
│                                             │
│  AgentLoop   Memory   Scheduler   Models    │
│                                             │
│  (imports only: ports.py, models.py)        │
└─────────────────┬───────────────────────────┘
                  │ Ports (Python Protocols)
       ┌──────────┼──────────┐
       │          │          │
  ┌────▼───┐ ┌────▼───┐ ┌────▼───┐
  │ LLM    │ │Channel │ │ Tool   │
  │Adapter │ │Adapter │ │Adapter │
  ├────────┤ ├────────┤ ├────────┤
  │openai  │ │cli     │ │shell   │
  │        │ │matrix  │ │files   │
  │        │ │email   │ │search  │
  │        │ │        │ │mcp     │
  └────────┘ └────────┘ │spawn   │
                        └────────┘
       ┌──────────┐
       │Persistence│
       │ Adapter  │
       ├──────────┤
       │jsonl/json│
       └──────────┘
```

## Project Structure

```
squidbot/
├── squidbot/
│   ├── core/
│   │   ├── ports.py        # All Protocol interfaces (no external imports)
│   │   ├── models.py       # Pydantic data models (Message, Session, etc.)
│   │   ├── agent.py        # Agent loop (LLM ↔ tool execution)
│   │   ├── memory.py       # Memory management (history + memory.md)
│   │   ├── scheduler.py    # Cron scheduler
│   │   └── registry.py     # Tool registry
│   ├── adapters/
│   │   ├── llm/
│   │   │   └── openai.py   # OpenAI-compatible LLM adapter
│   │   ├── channels/
│   │   │   ├── cli.py      # Interactive CLI channel
│   │   │   ├── matrix.py   # Matrix/Element channel
│   │   │   └── email.py    # IMAP/SMTP email channel
│   │   ├── tools/
│   │   │   ├── shell.py    # Shell command execution
│   │   │   ├── files.py    # File read/write/edit
│   │   │   ├── web_search.py  # Web search (SearXNG/DuckDuckGo/Brave)
│   │   │   ├── mcp.py      # MCP server client
│   │   │   └── spawn.py    # Sub-agent spawn tool
│   │   └── persistence/
│   │       └── jsonl.py    # JSON/JSONL file persistence
│   ├── config/
│   │   └── schema.py       # Pydantic Settings configuration schema
│   └── cli/
│       └── main.py         # cyclopts CLI entry points
├── tests/
│   ├── core/               # Pure unit tests, no external dependencies
│   │   ├── test_agent.py
│   │   ├── test_memory.py
│   │   └── test_scheduler.py
│   └── integration/        # Integration tests (require API keys / services)
│       └── test_openai.py
├── workspace/              # Default user workspace (committed skeleton)
│   └── AGENTS.md           # Default system prompt / agent instructions
├── pyproject.toml
└── README.md
```

## Port Interfaces (core/ports.py)

All interfaces use Python's `typing.Protocol` for structural subtyping.
No abstract base classes — duck typing with static verification via mypy.

```python
class LLMPort(Protocol):
    """Interface for language model communication."""
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        *,
        stream: bool = True,
    ) -> AsyncIterator[LLMChunk]: ...

class ChannelPort(Protocol):
    """Interface for inbound/outbound message channels."""
    async def receive(self) -> AsyncIterator[InboundMessage]: ...
    async def send(self, message: OutboundMessage) -> None: ...
    async def send_typing(self, session_id: str) -> None: ...  # optional indicator

class ToolPort(Protocol):
    """Interface for agent tools."""
    name: str
    description: str
    parameters: dict  # JSON Schema

    async def execute(self, **kwargs) -> ToolResult: ...

class MemoryPort(Protocol):
    """Interface for session persistence."""
    async def load_history(self, session_id: str) -> list[Message]: ...
    async def append_message(self, session_id: str, message: Message) -> None: ...
    async def load_memory_doc(self, session_id: str) -> str: ...
    async def save_memory_doc(self, session_id: str, content: str) -> None: ...
    async def load_cron_jobs(self) -> list[CronJob]: ...
    async def save_cron_jobs(self, jobs: list[CronJob]) -> None: ...
```

## Agent Loop (core/agent.py)

The agent loop is a pure async function that takes ports as dependencies.
It has no knowledge of HTTP, files, or external services.

```
InboundMessage
     │
     ▼
Load session history + memory.md
     │
     ▼
Build messages: [system_prompt + memory.md, history, user_message]
     │
     ▼
     ┌──────────────────────────────┐
     │         LLM LOOP             │
     │                              │
     │  llm.chat(messages, tools)   │
     │         │                    │
     │    ┌────▼────┐               │
     │    │ chunk   │               │
     │    │ type?   │               │
     │    └────┬────┘               │
     │    text │    │ tool_call      │
     │         │    ▼               │
     │  stream │  execute tool      │
     │  to     │  append result     │
     │  channel│  loop continues ───┘
     │         │
     └─────────┘
     │
     ▼
Append final exchange to history
     │
     ▼
Check token limit → prune old messages if needed
     │
     ▼
OutboundMessage sent
```

**Token Pruning:** When history exceeds `max_context_tokens`, the oldest non-system messages
are dropped. A warning is injected into the context before pruning to prompt the agent to
consolidate important information into `memory.md`.

## Memory System

Two-layer design:

**Short-term (in-session):** Complete conversation history stored as JSONL, one message per
line. Loaded at session start, appended after each exchange.

**Long-term (cross-session):** A `memory.md` file per session managed by the agent itself
via a dedicated `memory_write` tool call. The content is injected into every system prompt.
The agent decides what is worth preserving — this is intentional and explicit.

**No automatic summarization.** The tradeoff is accepted: automatic summarization is complex,
error-prone (nanobot-redux had consolidation bugs), and opaque. The `memory.md` approach is
transparent and debuggable. The memory system sits behind `MemoryPort` and can be replaced
later with a summarizing implementation without touching the core.

## Data Models (core/models.py)

```python
@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[ContentBlock]
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class Session:
    id: str           # "{channel_type}:{sender_id}"
    channel: str
    sender_id: str
    created_at: datetime

@dataclass
class CronJob:
    id: str
    name: str
    message: str
    schedule: str     # cron expression or "every N seconds"
    timezone: str
    enabled: bool
    last_run: datetime | None
```

## Configuration (config/schema.py)

Location: `~/.squidbot/config.json` (overridable via `SQUIDBOT_CONFIG` env var).
Per-field environment variable overrides supported via Pydantic Settings.

```json
{
  "llm": {
    "api_base": "https://openrouter.ai/api/v1",
    "api_key": "sk-or-...",
    "model": "anthropic/claude-opus-4-5",
    "max_tokens": 8192,
    "max_context_tokens": 100000
  },
  "agents": {
    "workspace": "~/.squidbot/workspace",
    "system_prompt_file": "AGENTS.md",
    "restrict_to_workspace": true
  },
  "tools": {
    "shell": { "enabled": true },
    "files": { "enabled": true },
    "web_search": {
      "enabled": false,
      "provider": "searxng",
      "url": "https://searxng.example.com",
      "api_key": null
    },
    "mcp_servers": {}
  },
  "channels": {
    "matrix": {
      "enabled": false,
      "homeserver": "https://matrix.org",
      "user_id": "@bot:matrix.org",
      "access_token": "syt_...",
      "device_id": "SQUIDBOT01",
      "allow_from": [],
      "group_policy": "mention"
    },
    "email": {
      "enabled": false,
      "imap_host": "imap.gmail.com",
      "imap_port": 993,
      "smtp_host": "smtp.gmail.com",
      "smtp_port": 587,
      "username": "bot@gmail.com",
      "password": "...",
      "from_address": "bot@gmail.com",
      "allow_from": []
    }
  }
}
```

## Security Model

**Trust + workspace restriction** — appropriate for a single-user personal assistant.

- `restrict_to_workspace: true` limits all file operations to the configured workspace path
- Shell commands run on the host — the user trusts their own setup
- `allow_from` whitelists per channel (empty = allow all, non-empty = explicit allowlist)
- No pairing codes or complex auth — for personal use, allowlists are sufficient
- TLS verification always on by default for all HTTP clients

## Sub-Agents (tools/spawn.py)

The `spawn` tool creates a child `AgentLoop` with its own session context.
The parent agent blocks until the sub-agent completes and receives the result.
Sub-agents share the same LLM and tool adapters but have isolated sessions.

Use cases: long research tasks, parallel work, isolated code execution.

```
Parent AgentLoop
    │
    │ tool_call: spawn(task="...", context="...")
    ▼
SubSession created (parent_id=parent.session.id)
    │
Child AgentLoop runs to completion
    │
    ▼
Result returned as tool_result to parent
```

## Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.14 |
| Data validation | Pydantic v2 |
| Configuration | pydantic-settings |
| LLM client | openai (>=1.0, OpenAI-compatible) |
| Async runtime | asyncio (stdlib) |
| HTTP client | httpx |
| Matrix protocol | matrix-nio |
| MCP client | mcp |
| CLI framework | cyclopts |
| Build tool | uv |
| Linter/formatter | ruff |
| Type checker | mypy |
| Test runner | pytest + pytest-asyncio |

## Persistence Layout

```
~/.squidbot/
├── config.json              # User configuration
├── sessions/                # Conversation histories
│   └── <session-id>.jsonl   # One message per line (JSONL)
├── memory/                  # Long-term memory documents
│   └── <session-id>/
│       └── memory.md        # Agent-maintained memory file
└── cron/
    └── jobs.json            # Scheduled task definitions
```

Session IDs are derived from channel type and sender: `matrix:@user:matrix.org`,
`email:user@example.com`, `cli:local`.

## CLI Commands

```
squidbot onboard              # Interactive setup wizard
squidbot agent                # Start interactive CLI chat
squidbot agent -m "..."       # Single message, then exit
squidbot gateway              # Start gateway (all enabled channels)
squidbot status               # Show configuration and channel status
squidbot cron list            # List scheduled jobs
squidbot cron add             # Add a new cron job
squidbot cron remove <id>     # Remove a cron job
```

## Non-Goals (YAGNI)

The following are explicitly out of scope for the initial implementation:
- Voice/speech (TTS/STT)
- Web UI / dashboard
- Multi-user support
- Webhook endpoints
- Container sandboxing (deferred, extractable via ToolPort)
- Telegram, Discord, WhatsApp, Slack channels (can be added as adapters later)
- ClawHub / skill registry integration
- Agent social networks
