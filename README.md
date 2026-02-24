# squidbot

A lightweight personal AI assistant. Hexagonal architecture, multi-channel, multi-model.

## Features

- **Multi-channel** — interactive CLI, Matrix/Element, IMAP/SMTP email
- **Multi-model LLM pools** — named pools with ordered fallback; define providers, models, and pools independently
- **Skills system** — on-demand skill loading, agent-created skills, hot-reload without restart
- **Tools** — shell commands, file read/write/edit, web search, memory write, MCP servers, sub-agents (spawn)
- **Heartbeat** — proactive background checks on a configurable schedule and time window
- **Cron scheduler** — recurring tasks with cron expressions or interval syntax
- **Long-term memory** — two-level: global `MEMORY.md` (agent-curated, cross-channel) + global conversation summary (auto-generated from `history.jsonl`); meta-consolidation compresses summaries via LLM when they grow large
- **Hexagonal architecture** — ports & adapters, `mypy --strict`, 382 tests

## Installation

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install /path/to/squidbot
```

After code changes:

```bash
uv tool install --reinstall /path/to/squidbot
```

## Configuration

Default location: `~/.squidbot/squidbot.yaml`. Override with `SQUIDBOT_CONFIG`.

```yaml
llm:
  default_pool: "smart"

  providers:
    openrouter:
      api_base: "https://openrouter.ai/api/v1"
      api_key: "sk-or-..."
    local:
      api_base: "http://localhost:11434/v1"
      api_key: ""

  models:
    opus:
      provider: openrouter
      model: "anthropic/claude-opus-4-5"
      max_tokens: 8192
      max_context_tokens: 200000
    haiku:
      provider: openrouter
      model: "anthropic/claude-haiku-4-5"
      max_tokens: 4096
      max_context_tokens: 200000
    llama:
      provider: local
      model: "llama3.2"
      max_tokens: 2048
      max_context_tokens: 8192

  pools:
    smart:
      - model: opus
      - model: haiku   # fallback if opus fails
    fast:
      - model: haiku
      - model: llama

agents:
  workspace: "~/.squidbot/workspace"   # bootstrap files live here
  restrict_to_workspace: true
  consolidation_threshold: 100         # summarize history when this many new messages accumulate since last consolidation
  keep_recent_ratio: 0.2               # fraction of threshold kept verbatim after consolidation (e.g. 0.2 = 20 messages when threshold is 100)

  heartbeat:
    enabled: true
    interval_minutes: 30
    pool: "fast"                        # optional — defaults to llm.default_pool
    active_hours_start: "08:00"
    active_hours_end: "22:00"
    timezone: "Europe/Berlin"           # or "local"
    prompt: "Check HEARTBEAT.md for outstanding tasks."

skills:
  extra_dirs: []                        # additional skill search paths

tools:
  shell:
    enabled: true

  files:
    enabled: true

  web_search:
    enabled: false
    provider: "duckduckgo"             # or "searxng" or "brave"
    url: ""                            # required for searxng
    api_key: ""                        # required for brave

  search_history:
    enabled: true                      # search past conversations across all sessions

  mcp_servers:
    github:
      transport: "stdio"
      command: "uvx"
      args: ["mcp-server-github"]
    # my-service:
    #   transport: "http"
    #   url: "http://localhost:8080/mcp"

  spawn:
    enabled: true
    profiles:
      researcher:
        pool: "smart"                   # optional — defaults to llm.default_pool
        bootstrap_files:                # overrides default sub-agent allowlist
          - "SOUL.md"
          - "AGENTS.md"
        system_prompt_file: "RESEARCHER.md"   # loaded from workspace, appended
        system_prompt: ""                     # inline, appended last
        tools: []                             # empty = all tools

channels:
  matrix:
    enabled: false
    homeserver: "https://matrix.org"
    user_id: "@bot:matrix.org"
    access_token: "syt_..."
    device_id: "SQUIDBOT01"
    room_ids:
      - "!roomid:matrix.org"
    group_policy: "mention"             # open | mention | allowlist
    allowlist: []

  email:
    enabled: false
    imap_host: "imap.gmail.com"
    imap_port: 993
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    username: "bot@gmail.com"
    password: "..."
    from_address: "bot@gmail.com"
    allow_from: []
    tls: true
    tls_verify: true
```

## CLI

```
squidbot onboard              Interactive setup wizard (idempotent — re-run to update config)
squidbot agent                Start interactive CLI chat (Rich UI)
squidbot agent -m "..."       Single message, then exit
squidbot gateway              Start gateway (all enabled channels)
squidbot status               Show configuration summary and pool info

squidbot cron list            List scheduled jobs
squidbot cron add             Add a new cron job
squidbot cron remove <id>     Remove a cron job

squidbot skills list          List all discovered skills and their availability
```

## Architecture

Hexagonal (Ports & Adapters). The core domain has zero knowledge of external services.
All external dependencies are accessed through `Protocol` interfaces (Ports).
Concrete implementations (Adapters) plug into these ports.
Dependency direction: `CLI / Adapters → Ports ← Core`.

```
┌─────────────────────────────────────────────────────┐
│                       CORE                          │
│  AgentLoop   Memory   Scheduler   Models   Skills   │
└─────────────────────┬───────────────────────────────┘
                      │ Ports (Python Protocols)
       ┌──────────────┼──────────────┐
       │              │              │
  ┌────▼───┐     ┌────▼───┐    ┌────▼────┐
  │  LLM   │     │Channel │    │  Tool   │
  │Adapter │     │Adapter │    │ Adapter │
  ├────────┤     ├────────┤    ├─────────┤
  │openai  │     │cli     │    │shell    │
  │pool    │     │matrix  │    │files    │
  │        │     │email   │    │search   │
  └────────┘     └────────┘    │mcp      │
                               │spawn    │
  ┌─────────┐   ┌──────────┐   └─────────┘
  │Persist. │   │ Skills   │
  │ Adapter │   │ Adapter  │
  ├─────────┤   ├──────────┤
  │jsonl    │   │fs        │
  └─────────┘   └──────────┘
```

**LLM pools:** `PooledLLMAdapter` wraps an ordered list of `OpenAIAdapter` instances. On any
error the next model is tried. `AuthenticationError` is additionally logged at WARNING level.

**Skills:** Directories containing a `SKILL.md` file. Three-tier loading: metadata always in
system prompt, full body loaded on demand by the agent, bundled resources read as needed.
Skills with `always: true` are fully injected into every system prompt. Hot-reloaded via
mtime polling — no restart needed after creating or editing a skill.

**Memory system:**

Two-level persistence, global across all channels:

- **Global memory** (`~/.squidbot/workspace/MEMORY.md`) — agent-curated notes visible in every
  session under `## Your Memory`. Written by the agent via the `memory_write` tool (available
  in all channels: CLI, Matrix, Email, cron, heartbeat). Persists facts, preferences, and
  ongoing projects across all channels.
- **Global summary** (`~/.squidbot/memory/summary.md`) — auto-generated when conversation
  history exceeds `consolidation_threshold`. Covers all channels; messages are labelled with
  `[channel / sender]` for attribution. The agent cannot write these directly; the system
  appends a new summary chunk after each consolidation cycle. When summaries grow beyond ~600
  words, meta-consolidation recompresses the full summary via LLM rather than discarding old
  entries.
- **Consolidation cursor** (`~/.squidbot/history.meta.json`) — tracks the last consolidated
  message index so restarts don't re-summarise already-processed history.

**Persistence layout:**

```
~/.squidbot/
├── squidbot.yaml
├── history.jsonl              # Global conversation history — all channels, append-only
├── history.meta.json          # Global consolidation cursor
├── memory/
│   └── summary.md             # Auto-generated global summary (all channels)
└── cron/jobs.json             # Scheduled task definitions

~/.squidbot/workspace/
├── MEMORY.md           # Global cross-channel memory (agent-curated via memory_write)
├── BOOTSTRAP.md        # First-run ritual: identity interview (self-deletes when done)
├── SOUL.md             # Bot values, character, operating principles — loaded first each session
├── IDENTITY.md         # Bot name, creature, vibe, emoji
├── USER.md             # Information about the user (built up over time)
├── AGENTS.md           # Operative instructions: tools, workflows, conventions
├── ENVIRONMENT.md      # Local setup notes: SSH hosts, devices, aliases (optional)
├── HEARTBEAT.md        # Optional standing checklist for heartbeat
└── skills/             # User-defined skills (override bundled by name)
```

## Development

```bash
uv sync                      # Install dependencies (including dev)
uv run pytest                # Run all tests
uv run ruff check .          # Lint
uv run ruff format .         # Format
uv run mypy squidbot/        # Type-check
```

## License

MIT — see [LICENSE](LICENSE).
