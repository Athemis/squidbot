# Session-Scoped Model and Pool Slash Commands - Design

## Problem

Users currently cannot inspect or switch LLM pool/model behavior from chat. They must
infer model routing from config and logs, which is slow during interactive use.

## Goal

Add deterministic slash commands for runtime visibility and temporary per-session pool
switching, without writing config files and without adding persistent state.

## Command Surface (YAGNI)

- `/model`
  - Show the currently active pool for the logical session.
  - Show the last actually used model for that logical session.
  - If no LLM request has happened in this logical session yet, return deterministic
    text indicating no model has been used yet.
- `/pool`
  - Show active pool and whether it comes from default or session override.
- `/pool list`
  - List configured pool names.
- `/pool use <name>`
  - Set a temporary pool override for the current logical session.
- `/pool reset`
  - Remove logical-session override and return to default pool.

No direct `/model use ...` command in v1. Model selection remains pool-driven.

## Authorization

Use existing slash authorization policy unchanged:

- CLI: allowed.
- Non-CLI: owner-only.

No new auth model for this feature.

## Architecture

### 1) Slash parsing

Extend `squidbot/core/slash_commands.py` with actions for `model` and `pool`, keeping
argument parsing minimal and deterministic.

### 2) AgentLoop runtime state

Add session-scoped in-memory state keyed by logical session ID:

- active pool override: `dict[str, str]`
- last used model ID: `dict[str, str]`

State is ephemeral and process-local.

### 3) LLM resolver integration

`AgentLoop` receives optional constructor dependencies:

- `default_pool_name: str | None`
- `resolve_llm: Callable[[str], LLMPort] | None`
- `list_pool_names: Callable[[], list[str]] | None`

For non-slash user turns, `AgentLoop` selects the effective pool (`override` or default),
resolves the LLM adapter for that pool, and uses it for the turn.

### 4) Last-used model tracking

To support `/model` with real runtime information:

- `OpenAIAdapter` exposes a lightweight method/property to return its model ID.
- `PooledLLMAdapter` tracks the model ID of the adapter that actually succeeded on
  the most recent call and exposes that value.
- `AgentLoop` reads this introspection value after each successful LLM turn and stores
  it in the logical-session map.

This keeps core decoupled from concrete adapter types (duck typing via optional method).

## Data Flow

1. User sends message.
2. Slash commands are parsed before any LLM call.
3. If slash command:
   - `/pool use` validates pool name against `list_pool_names`.
   - `/pool reset` removes override for current logical session.
   - `/pool` and `/model` render deterministic status text.
4. If normal user message:
   - determine logical session ID,
   - resolve effective pool,
   - resolve LLM adapter,
   - run turn,
   - capture last-used model for this logical session.

## Error Handling

- Missing pool name: `Usage: /pool use <name>`
- Unknown pool: `Error: pool '<name>' not found.`
- Pool switching unavailable (resolver not configured): deterministic error text.
- `/model` before first LLM turn in logical session: deterministic info text.

## Testing Strategy

- Parser tests for `/model`, `/pool`, `/pool list`, `/pool use`, `/pool reset`.
- Agent tests for:
  - pool override set/read/reset behavior,
  - override isolation across logical sessions (`/new`),
  - `/model` no-usage and post-usage cases,
  - unknown pool errors,
  - behavior when resolver/list callback is unavailable.
- Adapter tests for model introspection:
  - `OpenAIAdapter` reports model ID,
  - `PooledLLMAdapter` reports actually used fallback model.
- Regression tests for existing slash commands.

## Success Criteria

- Users can inspect last-used model with `/model`.
- Users can switch pool per logical session via `/pool use` and undo with `/pool reset`.
- Changes are temporary and in-memory only.
- Existing slash command behavior remains stable.
