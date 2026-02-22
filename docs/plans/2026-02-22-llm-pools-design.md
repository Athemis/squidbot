# LLM Pools Design

**Date:** 2026-02-22
**Status:** Approved

## Overview

Multi-model LLM pools with automatic fallback. Named pools hold an ordered list of
model references; the first model is tried first, and on any error the next is tried.
Heartbeat and spawn-profiles can each reference a different pool than the main agent.

Inspired by OpenClaw's model failover design, but simpler: no auth-profile rotation,
no exponential backoff cooldowns — just sequential fallback through the pool list.

## Config Schema

Three new layers: **providers** (API credentials), **models** (model + provider +
token limits), **pools** (ordered fallback lists). Breaking change: old
`llm.api_base / api_key / model / max_tokens / max_context_tokens` are removed.

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
      - model: haiku
    fast:
      - model: haiku
      - model: llama

agents:
  heartbeat:
    pool: "fast"   # optional — defaults to llm.default_pool

tools:
  spawn:
    profiles:
      researcher:
        pool: "smart"   # optional — defaults to llm.default_pool
```

## Architecture

```
_make_agent_loop(settings)
    │
    ├── _resolve_llm(settings, pool_name) → LLMPort
    │       ├── pool_name = settings.llm.default_pool
    │       ├── resolves models → OpenAIAdapter instances
    │       └── wraps in PooledLLMAdapter if len > 1, else returns single adapter
    │
    ├── agent_loop = AgentLoop(llm=main_llm, ...)
    │
    ├── heartbeat_llm = _resolve_llm(settings, hb.pool or default_pool)
    │   heartbeat = HeartbeatService(agent_loop, tracker, workspace, config,
    │                                llm_override=heartbeat_llm)
    │
    └── spawn_factory = SubAgentFactory(llm=main_llm, ..., profiles=profiles)
            └── SubAgentFactory.build(profile) → llm = _resolve_llm(profile.pool or default_pool)
```

## Components

### `squidbot/config/schema.py` — Breaking changes

Remove `LLMConfig`. Add:

```python
class LLMProviderConfig(BaseModel):
    """API endpoint credentials."""
    api_base: str
    api_key: str = ""

class LLMModelConfig(BaseModel):
    """A named model definition referencing a provider."""
    provider: str           # key in llm.providers
    model: str              # model identifier string
    max_tokens: int = 8192
    max_context_tokens: int = 100_000

class LLMPoolConfig(BaseModel):
    """Ordered fallback list — each entry is a model name."""
    # list of {"model": "<name>"} entries
    __root__: list[LLMPoolEntry]   # or use RootModel in pydantic v2

class LLMPoolEntry(BaseModel):
    model: str              # key in llm.models

class LLMConfig(BaseModel):
    """Root LLM configuration."""
    default_pool: str = "default"
    providers: dict[str, LLMProviderConfig] = Field(default_factory=dict)
    models: dict[str, LLMModelConfig] = Field(default_factory=dict)
    pools: dict[str, list[LLMPoolEntry]] = Field(default_factory=dict)
```

`HeartbeatConfig` gains:
```python
pool: str = ""  # empty = use llm.default_pool
```

`SpawnProfile` gains:
```python
pool: str = ""  # empty = use llm.default_pool
```

### `squidbot/adapters/llm/pool.py` — New file

`PooledLLMAdapter` wraps a list of `LLMPort` instances and tries them in order:

```python
class PooledLLMAdapter:
    def __init__(self, adapters: list[LLMPort]) -> None: ...

    async def chat(self, messages, tools, *, stream=True) -> AsyncIterator[...]:
        last_exc: Exception | None = None
        for i, adapter in enumerate(self._adapters):
            try:
                async for chunk in await adapter.chat(messages, tools, stream=stream):
                    yield chunk
                return
            except Exception as exc:
                if _is_auth_error(exc):
                    logger.warning("llm pool: auth error on model {} ({}), trying next",
                                   i, type(exc).__name__)
                else:
                    logger.info("llm pool: error on model {} ({}), trying next",
                                i, type(exc).__name__)
                last_exc = exc
        raise last_exc  # all models exhausted
```

`_is_auth_error(exc)` checks `type(exc).__name__` for `"AuthenticationError"` —
no openai import needed, works for any provider.

**Fallback rule:** All exceptions trigger fallback. `AuthenticationError` is additionally
logged at WARNING level. This matches the design decision to never silently swallow
auth failures — the user must see them even if a fallback model succeeds.

### `squidbot/cli/main.py` — `_resolve_llm()` helper

New function, called from `_make_agent_loop()`:

```python
def _resolve_llm(settings: Settings, pool_name: str) -> LLMPort:
    """
    Build an LLMPort from a named pool in settings.

    Returns a single OpenAIAdapter if the pool has one entry,
    or a PooledLLMAdapter wrapping multiple adapters if len > 1.
    Raises ValueError if pool or referenced models/providers are not found.
    """
    pool_entries = settings.llm.pools.get(pool_name)
    if not pool_entries:
        raise ValueError(f"LLM pool '{pool_name}' not found in config")

    adapters = []
    for entry in pool_entries:
        model_cfg = settings.llm.models.get(entry.model)
        if not model_cfg:
            raise ValueError(f"Model '{entry.model}' not found in llm.models")
        provider_cfg = settings.llm.providers.get(model_cfg.provider)
        if not provider_cfg:
            raise ValueError(f"Provider '{model_cfg.provider}' not found in llm.providers")
        adapters.append(OpenAIAdapter(
            api_base=provider_cfg.api_base,
            api_key=provider_cfg.api_key,
            model=model_cfg.model,
        ))

    if len(adapters) == 1:
        return adapters[0]
    return PooledLLMAdapter(adapters)
```

### `squidbot/core/heartbeat.py` — `llm_override` parameter

`HeartbeatService.__init__` gains an optional `llm_override: LLMPort | None = None`.
When set, the heartbeat passes it to `AgentLoop.run()` via a new optional `llm`
parameter. When `None`, heartbeat uses the main agent's LLM (current behaviour).

`AgentLoop.run()` gains `llm: LLMPort | None = None` — if provided, it's used for
this run instead of `self._llm`. This is the OpenClaw pattern: no second AgentLoop,
just a per-call override.

### `squidbot/adapters/tools/spawn.py` — `llm_override` in `SubAgentFactory`

`SubAgentFactory.build(profile_name)` resolves the pool from `profile.pool or
settings.llm.default_pool` via a `_resolve_llm` callable injected at construction:

```python
class SubAgentFactory:
    def __init__(self, ..., resolve_llm: Callable[[str], LLMPort]) -> None: ...

    def build(self, profile_name: str | None) -> AgentLoop:
        profile = self._profiles.get(profile_name) if profile_name else None
        pool = profile.pool if (profile and profile.pool) else self._default_pool
        llm = self._resolve_llm(pool)
        ...
```

`_make_agent_loop()` passes `functools.partial(_resolve_llm, settings)` as
`resolve_llm`. This avoids circular imports and keeps the factory testable.

## Wiring in `_make_agent_loop()`

```python
# main agent
default_pool = settings.llm.default_pool
main_llm = _resolve_llm(settings, default_pool)
agent_loop = AgentLoop(llm=main_llm, ...)

# heartbeat
hb_pool = settings.agents.heartbeat.pool or default_pool
hb_llm = _resolve_llm(settings, hb_pool)
# hb_llm is only different from main_llm if pool differs
heartbeat = HeartbeatService(..., llm_override=hb_llm if hb_pool != default_pool else None)

# spawn
spawn_factory = SubAgentFactory(
    ...,
    default_pool=default_pool,
    resolve_llm=functools.partial(_resolve_llm, settings),
)
```

## `status` command

Updated to show pool names instead of old single-model fields:

```
pools:     smart (2 models), fast (2 models)
default:   smart
```

## Validation

`Settings.model_post_init()` (or a `@model_validator`) checks:
- `llm.default_pool` exists in `llm.pools`
- Every pool entry's `model` exists in `llm.models`
- Every model's `provider` exists in `llm.providers`
- `agents.heartbeat.pool` (if set) exists in `llm.pools`
- Every `tools.spawn.profiles[*].pool` (if set) exists in `llm.pools`

Raises `ValueError` with a descriptive message at startup, before any LLM call.

## Migration

Breaking change: old `llm.api_base / api_key / model / max_tokens /
max_context_tokens` fields are removed from `LLMConfig`. Existing configs must be
migrated to the new schema. The `onboard` wizard is updated to write the new format.

## Testing

**`tests/core/test_config.py`**
- Valid pool config loads correctly
- Missing `default_pool` → `ValueError`
- Pool entry referencing unknown model → `ValueError`
- Model referencing unknown provider → `ValueError`
- `heartbeat.pool` referencing unknown pool → `ValueError`

**`tests/adapters/llm/test_pool.py`** (new)
- Single-adapter pool: delegates directly, no wrapping overhead
- Two-adapter pool: first succeeds → second never called
- First raises generic error → second called, WARNING not logged
- First raises `AuthenticationError` → second called, WARNING logged
- Both raise → last exception re-raised
- Auth error name detection: `AuthenticationError`, `openai.AuthenticationError`

**`tests/adapters/test_llm_wiring.py`** (new)
- `_resolve_llm` with valid config → correct adapter type
- `_resolve_llm` with unknown pool → `ValueError`
- Heartbeat gets different LLM when `pool` differs from `default_pool`
- Heartbeat gets same LLM (no override) when `pool` is empty or matches default

**`tests/adapters/tools/test_spawn.py`** (existing)
- `SubAgentFactory.build()` calls `resolve_llm` with correct pool name
- Profile with explicit pool → `resolve_llm(profile.pool)`
- Profile without pool → `resolve_llm(default_pool)`
