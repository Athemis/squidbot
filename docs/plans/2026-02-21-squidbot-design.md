# squidbot — Design Document

**Date:** 2026-02-21  
**Updated:** 2026-03-02  
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
┌─────────────────────────────────────────────────────┐
│                       CORE                          │
│                                                     │
│  AgentLoop   Memory   Scheduler   Models   Skills   │
│                                                     │
│  (imports only: ports.py, models.py)                │
└─────────────────────┬───────────────────────────────┘
                      │ Ports (Python Protocols)
       ┌──────────────┼──────────────┐
       │              │              │
  ┌────▼───┐     ┌────▼───┐    ┌────▼────┐
  │ LLM    │     │Channel │    │  Tool   │
  │Adapter │     │Adapter │    │ Adapter │
  ├────────┤     ├────────┤    ├─────────┤
  │openai  │     │cli     │    │shell    │
  │pool    │     │rich_cli│    │files    │
  │        │     │matrix  │    │search   │
  └────────┘     │email   │    │mcp      │
                 └────────┘    │spawn    │
                               │memory_* │
                               │cron     │
                               │fetch_url│
  ┌─────────┐    ┌──────────┐  └─────────┘
  │Persist. │    │ Skills   │
  │ Adapter │    │ Adapter  │
  ├─────────┤    ├──────────┤
  │jsonl    │    │fs        │
  └─────────┘    └──────────┘

  ┌─────────────────────┐
  │  Dashboard Adapter  │  ← future, plugs into StatusPort
  ├─────────────────────┤
  │  web-ui / tui / ... │
  └─────────────────────┘
```

## Project Structure

```
squidbot/
├── squidbot/
│   ├── core/
│   │   ├── ports.py        # All Protocol interfaces (no external imports)
│   │   ├── models.py       # Pydantic data models (Message, Session, etc.)
│   │   ├── agent.py        # Agent loop (LLM ↔ tool execution)
│   │   ├── memory.py       # Memory management (global history + MEMORY.md)
│   │   ├── scheduler.py    # Cron scheduler
│   │   ├── cron_ops.py     # Cron job operations
│   │   ├── registry.py     # Tool registry
│   │   ├── skills.py       # SkillMetadata + XML summary builder
│   │   ├── text_extract.py # Text extraction utilities
│   │   └── heartbeat.py    # Heartbeat service
│   ├── adapters/
│   │   ├── llm/
│   │   │   ├── openai.py   # OpenAI-compatible LLM adapter
│   │   │   └── pool.py     # Pooled LLM adapter with fallback
│   │   ├── channels/
│   │   │   ├── cli.py      # CLI channels (basic + Rich/prompt-toolkit)
│   │   │   ├── matrix.py   # Matrix/Element channel
│   │   │   └── email.py    # IMAP/SMTP email channel
│   │   ├── tools/
│   │   │   ├── shell.py    # Shell command execution
│   │   │   ├── files.py    # read_file, write_file, list_files
│   │   │   ├── web_search.py  # Web search (DuckDuckGo/SearXNG/Brave)
│   │   │   ├── mcp.py      # MCP server client
│   │   │   ├── spawn.py    # spawn, spawn_await
│   │   │   ├── memory_write.py  # memory_write
│   │   │   ├── search_history.py # search_history
│   │   │   ├── cron.py     # cron_list, cron_add, cron_remove, cron_set_enabled
│   │   │   └── fetch_url.py # fetch_url
│   │   ├── persistence/
│   │   │   └── jsonl.py    # JSON/JSONL file persistence
│   │   ├── skills/
│   │   │   └── fs.py       # FsSkillsLoader: reads SKILL.md files
│   │   └── dashboard/      # Placeholder — future dashboard adapter(s)
│   │       └── __init__.py
│   ├── skills/             # Bundled skills (shipped with the package)
│   │   ├── memory/SKILL.md      # always: true — memory.md conventions
│   │   ├── cron/SKILL.md        # Scheduling instructions
│   │   ├── github/SKILL.md      # requires: [gh]
│   │   ├── git/SKILL.md         # requires: [git]
│   │   ├── task-extractor/SKILL.md  # Extract tasks from unstructured text
│   │   ├── inbox-triage/SKILL.md    # Prioritize inbox backlog into action buckets
│   │   ├── follow-up-manager/SKILL.md  # Track open loops and schedule follow-ups
│   │   ├── daily-briefing/SKILL.md  # Morning/start-of-day briefing
│   │   ├── weekly-review/SKILL.md   # Weekly reflection and planning reset
│   │   ├── meeting-prep-and-recap/SKILL.md  # Meeting agenda and recap structure
│   │   ├── decision-log/SKILL.md    # Decision history with rationale
│   │   ├── personal-ops-router/SKILL.md  # Route multi-step productivity requests
│   │   ├── summarize/SKILL.md   # Document/content summarization
│   │   ├── research/SKILL.md    # Structured research with web search
│   │   └── skill-creator/SKILL.md  # How to create new skills
│   ├── config/
│   │   └── schema.py       # Pydantic Settings configuration schema
│   ├── cli/
│   │   ├── main.py         # cyclopts CLI entry points
│   │   ├── onboard.py      # Interactive setup wizard
│   │   ├── gateway.py      # Gateway startup and channel management
│   │   ├── cron.py         # Cron subcommand handlers
│   │   └── skills.py       # Skills subcommand handlers
│   └── workspace/          # Bootstrap files bundled with the package
│       ├── AGENTS.md       # Operative instructions
│       ├── BOOTSTRAP.md    # First-run ritual (self-deletes when done)
│       ├── ENVIRONMENT.md  # Local setup notes (optional)
│       ├── IDENTITY.md     # Bot name, creature, vibe
│       ├── SOUL.md         # Bot values, character
│       └── USER.md         # Information about the user
├── tests/
│   ├── core/               # Pure unit tests, no external dependencies
│   │   ├── test_agent.py
│   │   ├── test_memory.py
│   │   ├── test_scheduler.py
│   │   ├── test_skills.py
│   │   ├── test_heartbeat.py
│   │   ├── test_registry.py
│   │   ├── test_cron_ops.py
│   │   ├── test_models.py
│   │   ├── test_ports.py
│   │   ├── test_text_extract.py
│   │   └── ...
│   ├── adapters/           # Adapter tests using unittest.mock
│   │   ├── channels/       # test_rich_cli.py, test_matrix.py, test_email.py
│   │   ├── llm/            # test_openai.py, test_pool.py
│   │   ├── persistence/    # test_jsonl.py, test_jsonl_global_memory.py
│   │   ├── tools/          # test_shell.py, test_files.py, test_cron_tools.py, …
│   │   ├── test_gateway_helpers.py
│   │   ├── test_bootstrap_wiring.py
│   │   └── ...
│   └── integration/        # Integration tests (placeholder)
├── squidbot/workspace/     # Bundled workspace templates
├── pyproject.toml
└── README.md
```

## Port Interfaces (core/ports.py)

All interfaces use Python's `typing.Protocol` for structural subtyping.
No abstract base classes — duck typing with static verification via mypy.

### LLMPort

```python
class LLMPort(Protocol):
    """Interface for language model communication."""
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        *,
        stream: bool = True,
    ) -> AsyncIterator[str | list[ToolCall] | tuple[list[ToolCall], str | None]]:
        """
        Send messages to the LLM and receive a response stream.

        Yields either:
        - str: a text chunk to be forwarded to the channel
        - list[ToolCall]: a complete set of tool calls (end of response)
        - tuple[list[ToolCall], str | None]: tool calls with optional reasoning content
        """
```

### ChannelPort

```python
class ChannelPort(Protocol):
    """Interface for inbound/outbound message channels."""
    streaming: bool  # True = stream chunks; False = collect then send

    def receive(self) -> AsyncIterator[InboundMessage]:
        """Yield inbound messages as they arrive."""

    async def send(self, message: OutboundMessage) -> None:
        """Send a message to the channel."""

    async def send_typing(self, session_id: str) -> None:
        """Send a typing indicator if the channel supports it."""
```

### ToolPort

```python
class ToolPort(Protocol):
    """Interface for agent tools."""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given arguments."""
```

### MemoryPort

```python
class MemoryPort(Protocol):
    """
    Interface for session state persistence.

    All operations are GLOBAL — no session_id parameters.
    History and memory are shared across all channels.
    """
    async def load_history(self, last_n: int | None = None) -> list[Message]:
        """Load messages from global history."""

    async def append_message(self, message: Message) -> None:
        """Append a single message to the global history."""

    async def load_global_memory(self) -> str:
        """Load the global cross-session memory document."""

    async def save_global_memory(self, content: str) -> None:
        """Overwrite the global memory document."""

    async def load_cron_jobs(self) -> list[CronJob]:
        """Load all scheduled jobs."""

    async def save_cron_jobs(self, jobs: list[CronJob]) -> None:
        """Persist the full list of scheduled jobs."""
```

### SkillsPort

```python
class SkillsPort(Protocol):
    """Interface for skill discovery and loading."""
    def list_skills(self) -> list[SkillMetadata]:
        """Return all discovered SkillMetadata objects (mtime-cached)."""

    def load_skill_body(self, name: str) -> str:
        """Return the full SKILL.md text for a named skill."""
```

### StatusPort

```python
class StatusPort(Protocol):
    """Interface for gateway status reporting."""
    def get_active_sessions(self) -> list[SessionInfo]: ...
    def get_channel_status(self) -> list[ChannelStatus]: ...
    def get_cron_jobs(self) -> list[CronJob]: ...
    def get_skills(self) -> list[SkillMetadata]: ...
```

## Data Models (core/models.py)

```python
@dataclass
class ToolCall:
    """A tool invocation requested by the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]

@dataclass
class ToolResult:
    """The result of executing a tool."""
    tool_call_id: str
    content: str
    is_error: bool = False

@dataclass
class Message:
    """A single message in a conversation."""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None       # set when role == "tool"
    reasoning_content: str | None = None  # LLM reasoning (e.g., Claude)
    timestamp: datetime = field(default_factory=datetime.now)
    channel: str | None = None            # Source channel (for labelled history)
    sender_id: str | None = None          # Sender identifier (for labelled history)

@dataclass
class Session:
    """A conversation session, identified by channel and sender."""
    channel: str
    sender_id: str
    created_at: datetime = field(default_factory=datetime.now, compare=False)

    @property
    def id(self) -> str:
        return f"{self.channel}:{self.sender_id}"

@dataclass
class InboundMessage:
    """A message received from a channel."""
    session: Session
    text: str
    received_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class OutboundMessage:
    """A message to be sent to a channel."""
    session: Session
    text: str
    attachment: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class ToolDefinition:
    """Definition of a tool that can be called by the LLM."""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object

@dataclass
class CronJob:
    """A scheduled task."""
    id: str
    name: str
    message: str
    schedule: str  # cron expression ("0 9 * * *") or interval ("every 3600")
    channel: str   # target session ID, e.g. "cli:local"
    enabled: bool = True
    timezone: str = "local"
    last_run: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class SessionInfo:
    """Runtime metadata for a session seen since gateway start."""
    session_id: str
    channel: str
    sender_id: str
    started_at: datetime
    message_count: int

@dataclass
class ChannelStatus:
    """Runtime status of a channel adapter."""
    name: str
    enabled: bool
    connected: bool
    error: str | None = None
```

**Note:** `SkillMetadata` lives in `core/skills.py`, not `models.py`, since it is
domain logic specific to the skills system.

## CLI Channels (adapters/channels/cli.py)

Two CLI channel implementations are provided:

### CliChannel

Basic streaming CLI channel using standard `input()`:
- `streaming = True` — text chunks sent immediately
- Simple `print()` output
- Minimal dependencies

### RichCliChannel

Enhanced CLI channel using **prompt-toolkit** and **Rich**:
- `streaming = False` — collects full response before rendering
- **prompt-toolkit** for advanced input handling (multiline, history, key bindings)
- **Rich** for Markdown rendering, syntax highlighting, and styled output
- Better UX for interactive use

Both channels use the same `Session(channel="cli", sender_id="local")`.

## Configuration (config/schema.py)

Location: `~/.squidbot/config.json` (overridable via `SQUIDBOT_CONFIG` env var).
Per-field environment variable overrides supported via Pydantic Settings.

```json
{
  "llm": {
    "default_pool": "smart",
    "providers": {
      "openrouter": {
        "api_base": "https://openrouter.ai/api/v1",
        "api_key": "sk-or-...",
        "supports_reasoning_content": false
      }
    },
    "models": {
      "opus": {
        "provider": "openrouter",
        "model": "anthropic/claude-opus-4-5",
        "max_tokens": 8192,
        "max_context_tokens": 200000
      }
    },
    "pools": {
      "smart": [{"model": "opus"}, {"model": "haiku"}]
    }
  },
  "agents": {
    "workspace": "~/.squidbot/workspace",
    "restrict_to_workspace": true,
    "history_context_messages": 80,
    "heartbeat": {
      "enabled": true,
      "interval_minutes": 30,
      "pool": "",
      "prompt": "",
      "active_hours_start": "00:00",
      "active_hours_end": "24:00",
      "timezone": "local"
    }
  },
  "skills": {
    "extra_dirs": []
  },
  "tools": {
    "shell": { "enabled": true },
    "files": { "enabled": true },
    "web_search": {
      "enabled": false,
      "provider": "searxng",
      "url": "",
      "api_key": ""
    },
    "fetch_url": { "enabled": true },
    "search_history": { "enabled": true },
    "mcp_servers": {},
    "spawn": {
      "enabled": false,
      "profiles": {
        "researcher": {
          "pool": "smart",
          "bootstrap_files": ["SOUL.md", "AGENTS.md"],
          "system_prompt_file": "RESEARCHER.md",
          "system_prompt": "",
          "tools": []
        }
      }
    }
  },
  "channels": {
    "matrix": {
      "enabled": false,
      "homeserver": "https://matrix.org",
      "user_id": "@bot:matrix.org",
      "access_token": "syt_...",
      "device_id": "SQUIDBOT01",
      "room_ids": [],
      "group_policy": "mention",
      "allowlist": []
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
      "allow_from": [],
      "tls": true,
      "tls_verify": true,
      "imap_starttls": false,
      "smtp_starttls": true,
      "poll_interval_seconds": 60
    }
  },
  "owner": {
    "aliases": [
      {"address": "@user:matrix.org", "channel": "matrix"},
      {"address": "user@example.com"}
    ]
  }
}
```

**Key differences from earlier design:**
- **LLM configuration** now uses a three-tier hierarchy: providers → models → pools
- **Heartbeat** has rich configuration (pool, active hours, timezone)
- **Spawn profiles** allow per-profile LLM pools and bootstrap customization
- **Owner aliases** support scoped (channel-specific) and unscoped entries

## Memory System

**Global cross-channel design:** All history and memory is shared across channels.

**Two-layer design:**

**Short-term (global history):** Complete conversation history stored as JSONL in
`~/.squidbot/history.jsonl`, one message per line. Loaded at session start (limited
to `history_context_messages`), appended after each exchange.

**Long-term (cross-session):** A global `~/.squidbot/workspace/MEMORY.md` file managed
by the agent itself via the `memory_write` tool. The content is injected into every
system prompt under `## Your Memory`.

**Labelled history:** Messages in context are labelled with `[{channel} / {label}]`
where label is "owner" (if sender matches an owner alias), "assistant", or the
sender_id. This gives the agent context about who said what across channels.

**No automatic summarization.** The tradeoff is accepted: automatic summarization is complex,
error-prone, and opaque. The `MEMORY.md` approach is transparent and debuggable.
The `MemoryPort` abstraction allows future replacement without core changes.

## Skills System

Skills are directories containing a `SKILL.md` file — markdown instructions for the agent,
with YAML frontmatter for metadata. They are pure data, not executable code.

### Skill Format

```yaml
---
name: github
description: "Interact with GitHub — create PRs, manage issues, query CI status."
always: false        # true: full body injected into every system prompt
requires:
  bins: [gh]         # optional: skill is marked unavailable if binary not on PATH
  env: []            # optional: skill is marked unavailable if env var not set
metadata: {"squidbot": {"emoji": "🐙"}}
---

# GitHub Skill

[Full markdown instructions for the agent — loaded on demand via read_file]
```

### Three-Tier Loading

| Tier | What | When |
|---|---|---|
| 1. Metadata | `name` + `description` (~100 tokens per skill) | Always in system prompt as XML block |
| 2. SKILL.md body | Full markdown content | Agent reads via `read_file` when task matches |
| 3. Bundled resources | `scripts/`, `references/` subdirs | Agent reads/executes as needed |

Example XML block injected into system prompt:

```xml
<skills>
  <skill available="true">
    <name>github</name>
    <description>Interact with GitHub — create PRs, manage issues, query CI status.</description>
    <location>/path/to/squidbot/skills/github/SKILL.md</location>
  </skill>
  <skill available="false">
    <name>gh</name>
    <description>...</description>
    <location>...</location>
    <requires>CLI: gh</requires>
  </skill>
</skills>
```

### Skill Resolution

**Precedence:** `extra_dirs` → workspace skills → bundled skills. Higher priority
shadows lower by name.

**Availability:** Skills with unsatisfied `requires.bins` or `requires.env` are included
with `available="false"` and a `<requires>` hint.

**Always-skills:** Skills with `always: true` (e.g. `memory`) have their full body
injected unconditionally into the system prompt rather than listed in the XML summary.

### Skill Discovery: mtime Polling

`FsSkillsLoader` caches loaded skill metadata and re-reads from disk only when a file's
modification time (`mtime`) has changed. This means:

- Skills added or edited while the gateway is running are picked up automatically
- No restart required after creating a skill via `skill-creator`
- No unnecessary filesystem I/O on every agent call

The cache is keyed by `(path, mtime)`. On each `list_skills()` call, the loader stats
all SKILL.md files and invalidates any entry whose mtime has changed.

### Bundled Skills

```
squidbot/skills/                         # Bundled (read-only, shipped with package)
├── memory/SKILL.md      always: true    # memory.md conventions, always injected
├── cron/SKILL.md                        # Scheduling instructions
├── github/SKILL.md      requires: [gh]  # GitHub via gh CLI
├── git/SKILL.md         requires: [git] # Git operations
├── task-extractor/SKILL.md              # Extract tasks from unstructured text
├── inbox-triage/SKILL.md                # Prioritize inbox backlog
├── follow-up-manager/SKILL.md           # Follow-up tracking and reminders
├── daily-briefing/SKILL.md              # Daily briefing generation
├── weekly-review/SKILL.md               # Weekly review and planning reset
├── meeting-prep-and-recap/SKILL.md      # Meeting prep and recap workflow
├── decision-log/SKILL.md                # Decision capture with rationale
├── personal-ops-router/SKILL.md         # Route multi-step productivity requests
├── summarize/SKILL.md                   # Document/content summarization
├── research/SKILL.md                    # Structured research workflow
└── skill-creator/SKILL.md               # How to create new skills
```

**Note on `requires`:** The `requires_bins` and `requires_env` fields exist in `SkillMetadata`
and are fully supported by `FsSkillsLoader`. Skills with missing requirements render with
`available="false"` in the skills XML block.

## Agent Loop (core/agent.py)

The agent loop is a pure async function that takes ports as dependencies.
It has no knowledge of HTTP, files, or external services.

```
InboundMessage
     │
     ▼
Build message context (system + labelled history + user)
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
Append final exchange to global history
     │
     ▼
OutboundMessage sent
```

**Streaming strategy:** Each `ChannelPort` adapter declares `streaming: bool`. When `True`
(CLI), text chunks are forwarded to `channel.send()` as they arrive. When `False`
(Matrix, Email), chunks are accumulated and sent once at the end.

**MAX_TOOL_ROUNDS = 20:** Prevents infinite loops from buggy tool chains.

## Tool Inventory

All tools registered in `ToolRegistry`. Each file in `adapters/tools/` may expose one or more tools.

| Tool name(s) | File | Description |
|---|---|---|
| `read_file` | `files.py` | Read a file from the workspace |
| `write_file` | `files.py` | Write or overwrite a file in the workspace |
| `list_files` | `files.py` | List files and directories in the workspace |
| `shell` | `shell.py` | Execute a shell command on the host |
| `web_search` | `web_search.py` | Search the web via DuckDuckGo, SearXNG, or Brave |
| `fetch_url` | `fetch_url.py` | Fetch and extract text content from a URL |
| `memory_write` | `memory_write.py` | Overwrite the global `MEMORY.md` file |
| `search_history` | `search_history.py` | Full-text search of `history.jsonl` |
| `cron_list` | `cron.py` | List all scheduled cron jobs |
| `cron_add` | `cron.py` | Schedule a new cron job |
| `cron_remove` | `cron.py` | Remove a cron job by ID |
| `cron_set_enabled` | `cron.py` | Enable or disable a cron job |
| `spawn` | `spawn.py` | Launch a sub-agent task (fire-and-forget) |
| `spawn_await` | `spawn.py` | Launch a sub-agent task and wait for the result |
| *(dynamic)* | `mcp.py` | Tools exposed by configured MCP servers |

**Note on cron tools:** `cron_add` is a context-aware tool — it captures the current channel/session
as the default target when creating a new job. `cron_list`, `cron_remove`, and `cron_set_enabled`
are global tools with no session binding.

## LLM Pools

The `PooledLLMAdapter` implements sequential fallback across multiple models:

```python
pools:
  smart:
    - model: opus      # Try this first
    - model: haiku     # Fallback if opus fails
  fast:
    - model: haiku
    - model: llama
```

- On any error before the first chunk, the next model is tried
- `AuthenticationError` is logged at WARNING level even when fallback succeeds
- The `stream` parameter is respected across all adapters in the pool

## Bootstrap Files

The agent's system prompt is assembled from workspace files in fixed order:

### Main agent (loading order)

| File | Purpose |
|---|---|
| `SOUL.md` | Bot values, character, operating principles (bundled default) |
| `IDENTITY.md` | Bot name, creature, vibe, emoji (created during bootstrap) |
| `USER.md` | Information about the user (name, timezone, preferences) |
| `AGENTS.md` | Operative instructions: tools, workflows, conventions |
| `ENVIRONMENT.md` | Local setup notes: SSH hosts, devices, aliases |

Files are concatenated in this order, separated by `---`.
`BOOTSTRAP.md` is a one-time first-run ritual that self-deletes when complete.

### Sub-agents (default allowlist)

Sub-agents receive only `AGENTS.md` + `ENVIRONMENT.md` by default.
Per-profile overrides are available in `SpawnProfile`:

```yaml
tools:
  spawn:
    profiles:
      researcher:
        pool: "smart"
        bootstrap_files: ["SOUL.md", "AGENTS.md"]
        system_prompt_file: "RESEARCHER.md"
        system_prompt: "Focus on academic sources."
```

## Heartbeat

The gateway runs a `HeartbeatService` alongside channels and the cron scheduler. Every
`interval_minutes` (default: 30) it wakes the agent to check for outstanding tasks.

### Mechanism

1. Check `active_hours` — skip outside the configured time window.
2. Read `HEARTBEAT.md` from the workspace. If empty (only headings/whitespace), skip.
3. Send the heartbeat prompt to `AgentLoop` in the last active user's session.
4. If response starts/ends with `HEARTBEAT_OK` → silent drop + DEBUG log.
5. Otherwise → deliver the alert to the last active channel.

### Configuration

```json
{
  "agents": {
    "heartbeat": {
      "enabled": true,
      "interval_minutes": 30,
      "pool": "",
      "prompt": "",
      "active_hours_start": "00:00",
      "active_hours_end": "24:00",
      "timezone": "local"
    }
  }
}
```

## Persistence Layout

```
~/.squidbot/
├── config.json              # User configuration
├── history.jsonl            # Global conversation history — all channels, append-only
└── cron/
    └── jobs.json            # Scheduled task definitions

~/.squidbot/workspace/
├── MEMORY.md                # Global cross-channel memory (agent-curated)
├── BOOTSTRAP.md             # First-run ritual (deleted when done)
├── SOUL.md                  # Bot values, character
├── IDENTITY.md              # Bot name, creature, vibe
├── USER.md                  # Information about the user
├── AGENTS.md                # Operative instructions
├── ENVIRONMENT.md           # Local setup notes (optional)
├── HEARTBEAT.md             # Standing checklist for heartbeat (optional)
└── skills/                  # User-defined skills (override bundled by name)
```

## Security Model

**Trust + workspace restriction** — appropriate for a single-user personal assistant.

- `restrict_to_workspace: true` limits all file operations to the configured workspace path
- Shell commands run on the host — the user trusts their own setup
- `allowlist` per channel when `group_policy: allowlist` (empty = no filter for other policies)
- `owner.aliases` identifies the owner across channels for proper attribution
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

Profiles are configured in `tools.spawn.profiles` and can specify:
- `pool`: Which LLM pool to use (defaults to `llm.default_pool`)
- `bootstrap_files`: Override the default `[AGENTS.md, ENVIRONMENT.md]` allowlist
- `system_prompt_file`: Load additional prompt from workspace file
- `system_prompt`: Inline prompt appended last
- `tools`: Tool allowlist (empty = all tools)

## Dashboard (Future)

A dashboard is planned but not part of the initial implementation. The architecture is
designed to support it cleanly when the time comes.

The dashboard is a **read-mostly consumer** of existing ports — it observes gateway state
without modifying agent behaviour. It plugs in as a `DashboardAdapter` behind `StatusPort`.

`StatusPort` provides:
- `get_active_sessions()` — sessions seen since gateway start
- `get_channel_status()` — runtime channel health
- `get_cron_jobs()` — current scheduled jobs
- `get_skills()` — discovered skills with availability

The dashboard technology (web UI, TUI via Textual, etc.) is not yet decided.
The `adapters/dashboard/` directory is a placeholder.

## Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.14 |
| Data validation | Pydantic v2 |
| Configuration | pydantic-settings |
| LLM client | openai (>=2.0, OpenAI-compatible) |
| Async runtime | asyncio (stdlib, Python 3.14) |
| HTTP client | httpx |
| Matrix protocol | matrix-nio |
| Markdown → HTML | mistune |
| Image dimensions | Pillow |
| MIME detection | mimetypes (stdlib); python-magic optional |
| Web search | duckduckgo-search |
| MCP client | mcp |
| CLI framework | cyclopts |
| Terminal UI | rich |
| Terminal input | prompt-toolkit |
| YAML parsing | ruamel.yaml (YAML 1.2, round-trip safe) |
| Cron parsing | cronsim |
| Logging | loguru |
| Build tool | uv |
| Linter/formatter | ruff |
| Type checker | mypy |
| Test runner | pytest + pytest-asyncio |

## CLI Commands

```
squidbot onboard              # Interactive setup wizard (idempotent)
squidbot agent                # Start interactive CLI chat
squidbot agent -m "..."       # Single message, then exit
squidbot gateway              # Start gateway (all enabled channels)
squidbot status               # Show configuration and channel status

squidbot cron list            # List scheduled jobs
squidbot cron add             # Add a new cron job
squidbot cron remove <id>     # Remove a cron job

squidbot skills list          # List all discovered skills and their availability
```

## Non-Goals (YAGNI)

The following are explicitly out of scope for the initial implementation:

- Voice/speech (TTS/STT)
- Web UI / dashboard (architecture prepared, implementation deferred)
- Multi-user support
- Webhook endpoints
- Container sandboxing (deferred, extractable via ToolPort)
- Telegram, Discord, WhatsApp, Slack channels (can be added as adapters later)
- Skill registry / remote skill download (deferred, adapter-ready via SkillsPort)
- Agent social networks

## Changelog

### 2026-02-28 — Reconciled with Codebase

**Corrections applied:**

1. **Technology Stack:** `markdown-it-py` replaced by `mistune` (actual dependency in `pyproject.toml`).

2. **Project structure — tool comments:** `files.py`, `spawn.py`, and `cron.py` comments now list
   all exposed tool names explicitly (`read_file`/`write_file`/`list_files`, `spawn`/`spawn_await`,
   `cron_list`/`cron_add`/`cron_remove`/`cron_set_enabled`).

3. **Tool Inventory section added:** New section with a complete table of all tool names, their
   source file, and description — replaces scattered inline mentions.

4. **Config defaults corrected:**
   - `spawn.enabled`: `true` → `false` (spawn disabled by default)
   - `web_search.provider`: `"duckduckgo"` → `"searxng"` (actual code default)
   - Heartbeat `active_hours_start`/`end`: `"08:00"`/`"22:00"` → `"00:00"`/`"24:00"` (always-on default)
   - Heartbeat `prompt` field added (configurable heartbeat prompt)
   - Heartbeat `timezone` default corrected to `"local"`

5. **Bundled skills:** `[planned]` markers added for skills with placeholder content; note added
   explaining that `requires_bins`/`requires_env` exists in code but is not yet used.

6. **Test structure:** Expanded to show representative files across all subdirectories.

---

### 2026-02-28 — Design Document Updated

**Major changes from original design:**

1. **Memory system is fully global** — No per-session history or memory. All operations
   go through global `history.jsonl` and `workspace/MEMORY.md`. `MemoryPort` has no
   `session_id` parameters.

2. **LLM configuration is hierarchical** — Replaced flat `api_base`/`api_key`/`model`
   with providers → models → pools hierarchy. Added `PooledLLMAdapter` for fallback.

3. **Added new tool adapters:**
   - `memory_write` — Write to global MEMORY.md
   - `search_history` — Search past conversations
   - `cron` — Manage scheduled jobs via tools
   - `fetch_url` — Fetch and extract content from URLs

4. **Enhanced ChannelPort** — `receive()` returns `AsyncIterator[InboundMessage]`;
   `streaming` attribute controls delivery strategy.

5. **Enhanced LLMPort** — `chat()` yields `str | list[ToolCall] | tuple[...]` to support
   reasoning content (e.g., Claude's thinking blocks).

6. **Added heartbeat configuration** — Pool selection, active hours, timezone support.

7. **Added owner aliases** — Cross-channel owner identification for proper attribution.

8. **Added spawn profiles** — Configurable sub-agent profiles with custom pools,
   bootstrap files, and tool allowlists.

9. **SkillMetadata moved** — From `core/models.py` to `core/skills.py`.

10. **CLI modularized** — Split from single `main.py` into `onboard.py`, `gateway.py`,
    `cron.py`, `skills.py`.

11. **Workspace structure** — Bundled templates live in `squidbot/workspace/`, not
    separate from source. Includes `BOOTSTRAP.md` for first-run ritual.

12. **CronJob enhanced** — Added `metadata` field for extensibility.

13. **Message enhanced** — Added `reasoning_content` field for LLMs that expose
    thinking/reasoning separately from response content.

14. **Added prompt-toolkit** — RichCliChannel uses prompt-toolkit for enhanced
    terminal input with history, multiline support, and better UX.

---

### 2026-03-02 — Performance Optimizations

**14 bottlenecks eliminated across core, adapters, and gateway:**

1. **P0 — Heartbeat blocking I/O fixed:** `_read_heartbeat_file` was calling
   `Path.read_text()` directly on the event loop thread. Moved to `asyncio.to_thread`.

2. **JsonlMemory — startup mkdir consolidated:** Directory creation moved to
   `__init__`; path helpers no longer call `mkdir` on every operation.

3. **JsonlMemory — in-memory ring-buffer cache:** `load_history` stores the last
   `_CACHE_SIZE` messages in a `collections.deque`. Cache hits skip disk I/O entirely
   (~200–330× faster for typical workloads).

4. **JsonlMemory — batch write:** New `append_messages(msgs)` method opens the file
   and acquires the lock once per exchange instead of once per message (~3× faster).
   Opted into via `hasattr` in `MemoryManager.persist_exchange` to preserve the
   `MemoryPort` protocol boundary.

5. **MemoryManager — parallel I/O on message build:** `build_messages` uses
   `asyncio.gather` to load history and global memory concurrently (~2× faster when
   both are cold).

6. **MemoryManager — skills-XML cache:** `build_skills_xml` result is cached keyed
   on a tuple of `(name, location, available, always, description)` fingerprints.
   Avoids re-serialising the XML block on every agent call when skills haven't changed.

7. **AgentLoop — parallel tool execution:** `_append_tool_results` uses
   `asyncio.gather(return_exceptions=True)` to dispatch all tool calls concurrently.
   Scales linearly with the number of tools (8 tools × 50ms = 50ms total vs 400ms).

8. **AgentLoop — remove dict copy per chunk:** Eliminated `dict(outbound_metadata or {})`
   shallow copy that was created on every streamed text chunk.

9. **RichCliChannel — Console() cached:** `Console()` construction moved to `__init__`;
   previously a new instance was created on every `send()` call (~98× faster per send).

10. **EmailChannel — SSLContext cached:** `ssl.create_default_context()` moved to
    `__init__`; previously reconstructed on every SMTP send (~42,000× faster per send).

11. **SearchHistoryTool — substring pre-filter:** Lines in `history.jsonl` are checked
    for the raw query string before JSON parsing. Reduces CPU cost by 5–9× at typical
    hit rates.

12. **ReadFileTool — single `asyncio.to_thread` call:** `exists()` and `read_text()`
    combined into one thread dispatch, halving the number of event-loop round-trips.

13. **Gateway — parallel MCP server connections:** `_connect_mcp_servers` helper
    connects all configured MCP servers concurrently via `asyncio.gather`.

14. **Gateway — MemoryWriteTool singleton + OpenAI client cache:** `MemoryWriteTool`
    is now instantiated once per channel loop instead of once per message. `_resolve_llm`
    caches `AsyncOpenAI` client instances keyed on `(api_base, api_key)`.

**Benchmark results** (median of 5 runs, see `scripts/benchmark_perf.py`):

| Benchmark | Before | After | Speedup |
|-----------|--------|-------|---------|
| `load_history` cache hit (500 msgs) | 1.28 ms | 0.01 ms | **179×** |
| `load_history` cache hit (2000 msgs) | 1.55 ms | 0.00 ms | **331×** |
| `load_history` cache hit (10000 msgs) | 1.07 ms | 0.00 ms | **226×** |
| `persist_exchange` batch write | 0.78 ms | 0.27 ms | **2.9×** |
| `build_messages` parallel load (2×20ms I/O) | 40.48 ms | 20.41 ms | **2.0×** |
| Parallel tools (2 × 50ms) | 100.52 ms | 50.40 ms | **2.0×** |
| Parallel tools (4 × 50ms) | 201.07 ms | 50.53 ms | **4.0×** |
| Parallel tools (8 × 50ms) | 402.30 ms | 50.69 ms | **7.9×** |
| `search_history` (5000 msgs, 1% hits) | 24.28 ms | 2.72 ms | **8.9×** |
| `search_history` (5000 msgs, 50% hits) | 23.84 ms | 13.63 ms | **1.7×** |
| `Console()` cache (10 sends) | 0.23 ms | 0.00 ms | **98×** |
| `SSLContext` cache (10 sends) | 80.37 ms | 0.00 ms | **42,634×** |

**Architecture constraints preserved:** `MemoryPort` protocol unchanged; `core/`
changes limited to `MemoryManager` and `AgentLoop`; hexagonal boundary intact.
