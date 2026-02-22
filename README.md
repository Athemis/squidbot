# squidbot

A lightweight personal AI assistant. Hexagonal architecture, multi-channel, multi-model.

## Features

- **Multi-channel** — interactive CLI, Matrix/Element, IMAP/SMTP email
- **Multi-model LLM pools** — named pools with ordered fallback; define providers, models, and pools independently
- **Skills system** — on-demand skill loading, agent-created skills, hot-reload without restart
- **Tools** — shell commands, file read/write/edit, web search, MCP servers, sub-agents (spawn)
- **Heartbeat** — proactive background checks on a configurable schedule and time window
- **Cron scheduler** — recurring tasks with cron expressions or interval syntax
- **Hexagonal architecture** — ports & adapters, `mypy --strict`, 273 tests

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

**Persistence layout:**

```
~/.squidbot/
├── squidbot.yaml
├── sessions/           # Conversation histories (JSONL, one message per line)
├── memory/             # Agent-maintained memory.md per session
└── cron/jobs.json      # Scheduled task definitions

~/.squidbot/workspace/
├── BOOTSTRAP.md        # First-run ritual: identity interview (self-deletes when done)
├── IDENTITY.md         # Bot name, creature, vibe, emoji — loaded first each session
├── SOUL.md             # Bot values, character, operating principles
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
