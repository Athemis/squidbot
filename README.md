# squidbot

A lightweight personal AI assistant. Hexagonal architecture, multi-channel, multi-model.

[![Codecov](https://codecov.io/gh/Athemis/squidbot/branch/main/graph/badge.svg)](https://codecov.io/gh/Athemis/squidbot)

## Features

- **Multi-channel** — interactive CLI, Matrix/Element, IMAP/SMTP email
- **Multi-model LLM pools** — named pools with ordered fallback; define providers, models, and pools independently
- **Skills system** — on-demand skill loading, agent-created skills, hot-reload without restart
- **Tools** — shell commands, file read/write/edit, web search, memory write, MCP servers, sub-agents (spawn)
- **Slash commands** — cross-channel `/help`, `/new`, `/status`, and `/remember <text>`, handled in core without an LLM roundtrip (owner-only on non-CLI channels; always allowed on CLI)
- **Heartbeat** — proactive background checks on a configurable schedule and time window
- **Cron scheduler** — recurring tasks with cron expressions or interval syntax
- **Long-term memory** — manual-only: global `MEMORY.md` (agent-curated, cross-channel) plus global `history.jsonl`; use `search_history` for explicit recall of older details
- **Hexagonal architecture** — ports & adapters, `mypy --strict`, comprehensive test suite

## Installation

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

If your system has a newer CMake, `python-olm` may fail to build unless this is set:

```bash
export CMAKE_POLICY_VERSION_MINIMUM=3.5
```

`python-olm` also requires a C++ compiler (`g++`). If `g++-12` is not found but you have another version:

```bash
CXX=/usr/bin/g++ CMAKE_POLICY_VERSION_MINIMUM=3.5 uv tool install /path/to/squidbot
```

Or create a symlink (requires root):

```bash
sudo ln -s /usr/bin/g++ /usr/bin/g++-12
```

```bash
uv tool install /path/to/squidbot
```

After code changes:

```bash
uv tool install --reinstall /path/to/squidbot
```

You can also inline it per command:

```bash
CMAKE_POLICY_VERSION_MINIMUM=3.5 uv tool install --reinstall /path/to/squidbot
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
    # kimi-instant:
    #   provider: openrouter
    #   model: "moonshotai/Kimi-K2.5"
    #   temperature: 0.6
    #   top_p: 0.95
    #   extra_body:
    #     thinking:
    #       type: "disabled"

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
  history_context_messages: 80         # number of recent global history messages included in prompt context

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

### Model-specific inference parameters

You can set optional inference parameters per model under `llm.models.<name>`. These
parameters are passed through to the provider for that model only.

| Field | Type | Notes |
| --- | --- | --- |
| `temperature` | number | Sampling randomness. Do not set for OpenAI o-series models. |
| `top_p` | number | Nucleus sampling. Do not set for OpenAI o-series models. |
| `presence_penalty` | number | Penalizes introducing tokens already present in context. |
| `frequency_penalty` | number | Penalizes repeated token frequency in generated output. |
| `reasoning_effort` | string | Reasoning level for models that support it (for example: `low`, `medium`, `high`). |
| `extra_body` | mapping | Provider-specific request fields merged into the JSON request body. |
| `max_tokens` | integer | Per-request output cap for that model entry (forwarded only when explicitly configured in that model block). |

Provider support for these fields is model/API specific; unsupported fields may be rejected at runtime.

#### Kimi K2.5 (thinking vs instant)

Thinking is generally on by default. Use separate entries so pools can select either
a deeper thinking mode or a faster instant mode:

```yaml
llm:
  models:
    kimi-thinking:
      provider: openrouter
      model: "moonshotai/Kimi-K2.5"
      temperature: 1.0
      top_p: 0.95

    kimi-instant:
      provider: openrouter
      model: "moonshotai/Kimi-K2.5"
      temperature: 0.6
      top_p: 0.95
      extra_body:
        thinking:
          type: "disabled"
```

#### GLM-5 (preserve reasoning content)

Enable reasoning-content preservation on the provider, then define a model entry:

```yaml
llm:
  providers:
    zhipu:
      api_base: "https://open.bigmodel.cn/api/paas/v4"
      api_key: "your-zhipu-api-key"
      supports_reasoning_content: true

  models:
    glm-5-thinking:
      provider: zhipu
      model: "glm-5"
      temperature: 1.0
      max_tokens: 131072
      extra_body:
        thinking:
          type: "enabled"
          clear_thinking: false
```

#### OpenAI o-series (`reasoning_effort`)

For o-series models, prefer `reasoning_effort` and leave sampling controls unset.
Do not configure `temperature` or `top_p` for these models.

```yaml
llm:
  providers:
    openai:
      api_base: "https://api.openai.com/v1"
      api_key: "sk-..."

  models:
    o4-mini-fast:
      provider: openai
      model: "o4-mini"
      reasoning_effort: low

    o4-mini-deep:
      provider: openai
      model: "o4-mini"
      reasoning_effort: high
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

Interactive slash commands (available across CLI, Matrix, and Email):

Note: Slash commands are owner-only on non-CLI channels. CLI slash commands are always allowed.

- `/help` — list available slash commands
- `/new` — start a new logical conversation session for the current channel/session
- `/status` — show current channel/logical session status
- `/remember <text>` — append a memory note to global MEMORY.md

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

Manual-only persistence, global across all channels:

- **Global memory** (`~/.squidbot/workspace/MEMORY.md`) — agent-curated notes visible in every
  session under `## Your Memory`. Written by the agent via the `memory_write` tool (available
  in all channels: CLI, Matrix, Email, cron, heartbeat). Persists facts, preferences, and
  ongoing projects across all channels.
- **Global history** (`~/.squidbot/history.jsonl`) — append-only history across all channels,
  with entries labelled by channel/sender. Recent messages are included in prompt context,
  and older details are recalled explicitly with the `search_history` tool.
- **Session context reset** (`/new`) — starts a new logical session and disables automatic
  history backfill for the next turn. Global history remains append-only, and older details
  can still be pulled explicitly with `search_history`.

**Persistence layout:**

```
~/.squidbot/
├── squidbot.yaml
├── history.jsonl              # Global conversation history — all channels, append-only
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
