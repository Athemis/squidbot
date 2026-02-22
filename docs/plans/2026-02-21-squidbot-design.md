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
  │        │     │matrix  │    │files    │
  │        │     │email   │    │search   │
  └────────┘     └────────┘    │mcp      │
                               │spawn    │
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
│   │   ├── memory.py       # Memory management (history + memory.md)
│   │   ├── scheduler.py    # Cron scheduler
│   │   ├── registry.py     # Tool registry
│   │   └── skills.py       # SkillMetadata model + skill summary builder
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
│   │   ├── persistence/
│   │   │   └── jsonl.py    # JSON/JSONL file persistence
│   │   ├── skills/
│   │   │   └── fs.py       # FsSkillsLoader: reads SKILL.md files from disk
│   │   └── dashboard/      # Placeholder — future dashboard adapter(s)
│   │       └── __init__.py
│   ├── skills/             # Bundled skills (shipped with the package)
│   │   ├── memory/
│   │   │   └── SKILL.md    # always: true — memory.md conventions
│   │   ├── cron/
│   │   │   └── SKILL.md    # Scheduling instructions
│   │   ├── github/
│   │   │   └── SKILL.md    # requires: [gh]
│   │   ├── git/
│   │   │   └── SKILL.md    # requires: [git]
│   │   ├── python/
│   │   │   └── SKILL.md    # requires: [python3]
│   │   ├── web-search/
│   │   │   └── SKILL.md    # Web search best practices
│   │   ├── summarize/
│   │   │   └── SKILL.md    # Document/content summarization
│   │   ├── research/
│   │   │   └── SKILL.md    # Structured research with web search
│   │   └── skill-creator/
│   │       └── SKILL.md    # How to create new skills
│   ├── config/
│   │   └── schema.py       # Pydantic Settings configuration schema
│   └── cli/
│       └── main.py         # cyclopts CLI entry points
├── tests/
│   ├── core/               # Pure unit tests, no external dependencies
│   │   ├── test_agent.py
│   │   ├── test_memory.py
│   │   ├── test_scheduler.py
│   │   └── test_skills.py
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
    streaming: bool   # True if send() should be called per-chunk; False = collect then send
    async def receive(self) -> AsyncIterator[InboundMessage]: ...
    async def send(self, message: OutboundMessage) -> None: ...
    async def send_typing(self, session_id: str) -> None: ...

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

class SkillsPort(Protocol):
    """Interface for skill discovery and loading."""
    def list_skills(self) -> list[SkillMetadata]: ...
    def load_skill_body(self, name: str) -> str: ...  # full SKILL.md text

class StatusPort(Protocol):
    """
    Interface for gateway status — consumed by the future dashboard adapter.

    The gateway maintains a GatewayState object and exposes it via this port.
    Dashboard adapters read from StatusPort; they never write agent state directly.
    """
    def get_active_sessions(self) -> list[SessionInfo]: ...
    def get_channel_status(self) -> list[ChannelStatus]: ...
    def get_cron_jobs(self) -> list[CronJob]: ...
    def get_skills(self) -> list[SkillMetadata]: ...
```

## Agent Loop (core/agent.py)

The agent loop is a pure async function that takes ports as dependencies.
It has no knowledge of HTTP, files, or external services.

```
InboundMessage
     │
     ▼
Load session history + memory.md + skills summary
     │
     ▼
Build messages: [system_prompt + memory.md + skills XML, history, user_message]
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

**Streaming strategy:** Each `ChannelPort` adapter declares `streaming: bool`. When `True`
(CLI), text chunks are forwarded to `channel.send()` as they arrive from the LLM, giving a
typewriter feel. When `False` (Matrix, Email), chunks are accumulated and sent as a single
message at the end of the turn. The agent loop checks `channel.streaming` to decide which
path to take — no other logic changes.

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

The metadata block uses the key `"squidbot"`. The format is otherwise structurally compatible
with nanobot/OpenClaw skill conventions (which use `"nanobot"` / `"openclaw"` keys),
making manual skill porting straightforward.

### Three-Tier Loading

| Tier | What | When |
|---|---|---|
| 1. Metadata | `name` + `description` (~100 tokens per skill) | Always in system prompt as XML block |
| 2. SKILL.md body | Full markdown content | Agent reads via `read_file` when task matches |
| 3. Bundled resources | `scripts/`, `references/` subdirs | Agent reads/executes as needed |

The agent receives an `<skills>` XML block in every system prompt listing all discovered
skills with their availability. The agent is instructed: *"When the current task matches a
skill's description, read its SKILL.md with `read_file` before proceeding — do not attempt
the task from first principles when a skill covers it."*

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

**Precedence:** workspace skills override bundled skills by name. A user-defined
`~/.squidbot/workspace/skills/github/SKILL.md` replaces the bundled `github` skill entirely.

**Availability:** Skills with unsatisfied `requires.bins` or `requires.env` are included in
the XML with `available="false"` and a `<requires>` hint. The agent can still read them but
knows the prerequisite is missing.

**Always-skills:** Skills with `always: true` (e.g. `memory`) have their full body injected
unconditionally into the system prompt rather than listed in the XML summary.

### Skill Directories

```
squidbot/skills/                         # Bundled (read-only, shipped with package)
├── memory/SKILL.md      always: true    # memory.md conventions, always injected
├── cron/SKILL.md                        # Scheduling instructions
├── github/SKILL.md      requires: [gh]  # GitHub via gh CLI
├── git/SKILL.md         requires: [git] # Git operations
├── python/SKILL.md      requires: [python3]
├── web-search/SKILL.md                  # Web search best practices
├── summarize/SKILL.md                   # Document/content summarization
├── research/SKILL.md                    # Structured research workflow
└── skill-creator/SKILL.md               # How to create new skills

~/.squidbot/workspace/skills/            # User-defined (override bundled by name)
└── <name>/SKILL.md
```

### Skill Discovery: mtime Polling

`FsSkillsLoader` caches loaded skill metadata and re-reads from disk only when a file's
modification time (`mtime`) has changed. This means:

- Skills added or edited while the gateway is running are picked up automatically
- No restart required after creating a skill via `skill-creator`
- No unnecessary filesystem I/O on every agent call

The cache is keyed by `(path, mtime)`. On each `list_skills()` call, the loader stats
all SKILL.md files and invalidates any entry whose mtime has changed.

### skill-creator: Agent-Created Skills

The `skill-creator` bundled skill teaches the agent how to write new skills. When the user
asks the agent to "remember how I like to write emails" or "create a skill for my deployment
workflow", the agent:

1. Reads `skill-creator/SKILL.md` via `read_file`
2. Writes `~/.squidbot/workspace/skills/<name>/SKILL.md` via `write_file`
3. The new skill is auto-discovered on the next `list_skills()` call (mtime polling)

The `skill-creator` SKILL.md explains:
- The full SKILL.md format (frontmatter fields, body conventions)
- When to use `always: true` vs. on-demand loading
- How to write a good `description` field (the trigger criterion)
- The `squidbot` metadata key convention
- A template the agent fills in

Example interaction:

```
User:  "Create a skill for writing professional emails in German."

Agent: [reads skill-creator/SKILL.md]
       [writes ~/.squidbot/workspace/skills/email-german/SKILL.md]

       "Skill 'email-german' created. It will be available the next time
       the gateway starts. When you ask me to write a German email, I'll
       load its instructions automatically."
```

### Architecture Fit

Skills are read-only data consumed by `FsSkillsLoader` (implements `SkillsPort`). The
`MemoryManager` calls `SkillsPort.list_skills()` to build the XML block and injects always-
skill bodies into the system prompt. The core (`skills.py`) contains only the `SkillMetadata`
dataclass and the XML-summary builder — no filesystem I/O.

### Skills Registry (Future)

A `RegistrySkillsAdapter` can later be added behind `SkillsPort` to support downloading
skills from a remote registry. This is explicitly deferred. The adapter boundary ensures
the core and agent loop need no changes when this is added.

## Dashboard (Future)

A dashboard is planned but not part of the initial implementation. The architecture is
designed to support it cleanly when the time comes.

### Design Principle

The dashboard is a **read-mostly consumer** of existing ports — it observes gateway state
without modifying agent behaviour. It plugs in as a `DashboardAdapter` behind `StatusPort`.
No special-casing in the core is needed.

### GatewayState

The gateway process maintains a central `GatewayState` object updated by running components:

```python
@dataclass
class GatewayState:
    active_sessions: dict[str, SessionInfo]   # session_id → metadata
    channel_status:  dict[str, ChannelStatus] # channel name → connected/error
    cron_jobs:       list[CronJob]            # current job list
    skills:          list[SkillMetadata]      # discovered skills
    started_at:      datetime
```

`StatusPort` exposes read access to this object. The `GatewayState` is the single source
of truth for any future dashboard adapter.

### What the Dashboard Will Show

- **Status panel:** active sessions, channel health, uptime
- **Conversation history:** browse past exchanges per session
- **Memory viewer:** read and edit `memory.md` per session
- **Skill manager:** list skills, see availability, trigger skill-creator
- **Cron manager:** view jobs, next-run times, enable/disable

### Technology Decision (Deferred)

The dashboard technology (web UI served by the gateway, TUI via Textual, or something else)
is not yet decided. The `adapters/dashboard/` directory is a placeholder. The `StatusPort`
interface is the only architectural commitment made now — any dashboard implementation
simply implements that port.

## Data Models (core/models.py)

```python
@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None       # set when role == "tool"
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class Session:
    channel: str
    sender_id: str
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def id(self) -> str:
        return f"{self.channel}:{self.sender_id}"

@dataclass
class InboundMessage:
    session: Session
    text: str
    received_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Matrix keys: matrix_event_id, matrix_room_id, matrix_thread_root

@dataclass
class OutboundMessage:
    session: Session
    text: str
    attachment: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # Matrix keys: matrix_reaction, matrix_reply_to, matrix_thread_root

@dataclass
class CronJob:
    id: str
    name: str
    message: str
    schedule: str     # cron expression or "every N seconds"
    channel: str      # e.g. "cli:local" or "matrix:@user:matrix.org"
    timezone: str
    enabled: bool
    last_run: datetime | None

@dataclass
class SkillMetadata:
    name: str
    description: str
    location: Path         # absolute path to SKILL.md
    always: bool = False
    available: bool = True
    requires_bins: list[str] = field(default_factory=list)
    requires_env: list[str] = field(default_factory=list)
    emoji: str = ""

@dataclass
class SessionInfo:
    session_id: str
    channel: str
    sender_id: str
    started_at: datetime
    message_count: int

@dataclass
class ChannelStatus:
    name: str
    enabled: bool
    connected: bool
    error: str | None = None
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
    "restrict_to_workspace": true
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
      "allow_from": []
    }
  }
}
```

`skills.extra_dirs` allows additional skill search paths beyond the two standard locations
(bundled package skills and `{workspace}/skills/`).

## Security Model

**Trust + workspace restriction** — appropriate for a single-user personal assistant.

- `restrict_to_workspace: true` limits all file operations to the configured workspace path
- Shell commands run on the host — the user trusts their own setup
- `allowlist` per channel when `group_policy: allowlist` (empty = no filter for other policies)
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
| LLM client | openai (>=2.0, OpenAI-compatible) |
| Async runtime | asyncio (stdlib, Python 3.14) |
| HTTP client | httpx |
| Matrix protocol | matrix-nio |
| Markdown → HTML | markdown-it-py |
| Image dimensions | Pillow |
| MIME detection | mimetypes (stdlib); python-magic optional |
| Web search | duckduckgo-search |
| MCP client | mcp |
| CLI framework | cyclopts |
| Terminal UI | rich |
| YAML parsing | ruamel.yaml (YAML 1.2, round-trip safe) |
| Cron parsing | cronsim |
| Logging | loguru |
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

~/.squidbot/workspace/
├── SOUL.md                  # Bot personality, values, tone, identity (optional)
├── USER.md                  # Information about the user (optional)
├── AGENTS.md                # Operative instructions: tools, workflows, conventions
├── ENVIRONMENT.md           # Local setup notes: SSH hosts, devices, aliases (optional)
├── HEARTBEAT.md             # Standing checklist for heartbeat (optional)
└── skills/                  # User-defined skills (override bundled by name)
    └── <name>/
        └── SKILL.md
```

Session IDs are derived from channel type and sender: `matrix:@user:matrix.org`,
`email:user@example.com`, `cli:local`.

## Bootstrap Files

The agent's system prompt is assembled automatically from an ordered set of workspace files.
Missing files are silently skipped. The `system_prompt_file` config field is removed — the
file set is fixed and convention-based, inspired by OpenClaw.

### Main agent (loading order)

| File | Purpose |
|---|---|
| `SOUL.md` | Bot personality, values, tone, identity |
| `USER.md` | Information about the user (name, timezone, preferences) |
| `AGENTS.md` | Operative instructions: tools, workflows, conventions |
| `ENVIRONMENT.md` | Local setup notes: SSH hosts, devices, aliases |

Files are concatenated in this order, separated by `---`. If none exist, a minimal
fallback prompt is used.

### Sub-agents (default allowlist)

Sub-agents receive only `AGENTS.md` + `ENVIRONMENT.md` by default — no personality,
no user context. This matches OpenClaw's `MINIMAL_BOOTSTRAP_ALLOWLIST` pattern.

Per-profile overrides are available in `SpawnProfile`:

```yaml
tools:
  spawn:
    profiles:
      researcher:
        bootstrap_files: ["SOUL.md", "AGENTS.md"]  # replaces default allowlist
        system_prompt_file: "RESEARCHER.md"         # loaded and appended
        system_prompt: "Focus on academic sources." # inline, appended last
        pool: smart
```

Prompt assembly order for sub-agents:
1. `bootstrap_files` (profile list, or default `["AGENTS.md", "ENVIRONMENT.md"]`)
2. `system_prompt_file` (loaded from workspace, appended if present)
3. `system_prompt` (inline string, appended if set)

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
squidbot skills list          # List all discovered skills and their availability
```

## Heartbeat

The gateway runs a `HeartbeatService` alongside channels and the cron scheduler. Every
`interval_minutes` (default: 30) it wakes the agent to check for outstanding tasks.

### Mechanism

1. Check `activeHours` — skip outside the configured time window.
2. Read `HEARTBEAT.md` from the workspace. If the file is effectively empty (only blank
   lines and Markdown headings), skip the tick to avoid unnecessary API calls.
3. Send the heartbeat prompt to `AgentLoop.run()` in the last active user's session.
4. If the response is `HEARTBEAT_OK` (at start or end of reply) → silent drop + DEBUG log.
5. Otherwise → deliver the alert to the last active channel.

### `LastChannelTracker`

A lightweight object updated by the gateway on every inbound message. Stores the last
`ChannelPort` and `Session`. The `HeartbeatService` reads these when firing. If no user
has ever written (tracker empty), the tick is skipped.

### Configuration

```json
{
  "agents": {
    "heartbeat": {
      "enabled": true,
      "interval_minutes": 30,
      "prompt": "Read HEARTBEAT.md if it exists...",
      "active_hours_start": "08:00",
      "active_hours_end": "22:00",
      "timezone": "Europe/Berlin"
    }
  }
}
```

Timezone uses stdlib `zoneinfo` (no extra dependency). `"local"` uses the host timezone.

### HEARTBEAT.md

Optional file in the agent workspace. Think of it as a standing checklist:

```md
# Heartbeat checklist

- Quick scan: anything urgent in inboxes?
- If a task is blocked, note what is missing.
```

The agent can update this file itself via the `write_file` tool.

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
