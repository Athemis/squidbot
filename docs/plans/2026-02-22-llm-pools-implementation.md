# LLM Pools Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the flat `LLMConfig` with a three-layer provider/model/pool system, add `PooledLLMAdapter` with sequential fallback, and wire pool selection into heartbeat and spawn-profiles.

**Architecture:** Hexagonal — all new LLM logic lives in `adapters/llm/pool.py`; core only sees `LLMPort`. Config changes are breaking (old `llm.*` fields removed). `AgentLoop.run()` gains an optional `llm` override parameter used by heartbeat.

**Tech Stack:** Python 3.14, pydantic v2, loguru, uv/pytest/ruff/mypy

---

## Task 1: New config schema — providers, models, pools, pool on SpawnProfile and HeartbeatConfig

**Files:**
- Modify: `squidbot/config/schema.py`
- Modify: `tests/core/test_config.py`

**Step 1: Write the failing tests**

Replace the existing `test_default_llm_config` and `test_settings_from_dict` tests and add new ones. The old tests reference the removed fields so they will fail after schema change — update them now so they serve as the spec:

```python
# tests/core/test_config.py

from squidbot.config.schema import (
    HeartbeatConfig,
    LLMConfig,
    LLMModelConfig,
    LLMPoolEntry,
    LLMProviderConfig,
    Settings,
    SpawnProfile,
    SpawnSettings,
    ToolsConfig,
)


def test_llm_config_defaults():
    cfg = LLMConfig()
    assert cfg.default_pool == "default"
    assert cfg.providers == {}
    assert cfg.models == {}
    assert cfg.pools == {}


def test_llm_provider_config():
    p = LLMProviderConfig(api_base="https://openrouter.ai/api/v1", api_key="sk-test")
    assert p.api_base == "https://openrouter.ai/api/v1"
    assert p.api_key == "sk-test"


def test_llm_model_config_defaults():
    m = LLMModelConfig(provider="openrouter", model="anthropic/claude-opus-4-5")
    assert m.max_tokens == 8192
    assert m.max_context_tokens == 100_000


def test_llm_pool_entry():
    e = LLMPoolEntry(model="opus")
    assert e.model == "opus"


def test_settings_full_pool_config():
    raw = {
        "llm": {
            "default_pool": "smart",
            "providers": {
                "openrouter": {"api_base": "https://openrouter.ai/api/v1", "api_key": "sk-test"}
            },
            "models": {
                "opus": {"provider": "openrouter", "model": "anthropic/claude-opus-4-5"}
            },
            "pools": {
                "smart": [{"model": "opus"}]
            },
        }
    }
    s = Settings.model_validate(raw)
    assert s.llm.default_pool == "smart"
    assert s.llm.providers["openrouter"].api_key == "sk-test"
    assert s.llm.models["opus"].model == "anthropic/claude-opus-4-5"
    assert s.llm.pools["smart"][0].model == "opus"


def test_heartbeat_config_pool_default():
    cfg = HeartbeatConfig()
    assert cfg.pool == ""


def test_spawn_profile_pool_default():
    p = SpawnProfile()
    assert p.pool == ""


def test_spawn_profile_with_pool():
    p = SpawnProfile(system_prompt="You are a coder.", pool="fast")
    assert p.pool == "fast"
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/core/test_config.py -v
```
Expected: FAIL — `LLMProviderConfig`, `LLMModelConfig`, `LLMPoolEntry` not importable, old fields missing.

**Step 3: Implement the new schema**

In `squidbot/config/schema.py`:

1. Remove the old `LLMConfig` class entirely.
2. Add before the new `LLMConfig`:

```python
class LLMProviderConfig(BaseModel):
    """API endpoint credentials for an LLM provider."""

    api_base: str
    api_key: str = ""


class LLMModelConfig(BaseModel):
    """A named model definition referencing a provider."""

    provider: str
    model: str
    max_tokens: int = 8192
    max_context_tokens: int = 100_000


class LLMPoolEntry(BaseModel):
    """One entry in a pool's fallback list — references a named model."""

    model: str


class LLMConfig(BaseModel):
    """Root LLM configuration using the provider/model/pool hierarchy."""

    default_pool: str = "default"
    providers: dict[str, LLMProviderConfig] = Field(default_factory=dict)
    models: dict[str, LLMModelConfig] = Field(default_factory=dict)
    pools: dict[str, list[LLMPoolEntry]] = Field(default_factory=dict)
```

3. Add `pool: str = ""` to `HeartbeatConfig`.
4. Add `pool: str = ""` to `SpawnProfile`.

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/core/test_config.py -v
```
Expected: new config tests PASS; other tests that used old `LLMConfig` fields will now fail — that's expected and handled in Task 2.

**Step 5: Commit**

```bash
git add squidbot/config/schema.py tests/core/test_config.py
git commit -m "feat: replace LLMConfig with provider/model/pool schema"
```

---

## Task 2: Fix all references to removed LLMConfig fields

**Files:**
- Modify: `squidbot/cli/main.py` (uses `settings.llm.api_base`, `.api_key`, `.model`)
- Modify: `tests/core/test_config.py` (already updated in Task 1)

The `status` command and `_run_agent` banner still reference old fields. Replace them with stubs for now — they'll be properly wired in Task 5.

**Step 1: Run the full test suite to see all breakage**

```bash
uv run pytest -q 2>&1 | head -50
```

**Step 2: Fix `_make_agent_loop()` temporarily**

In `squidbot/cli/main.py`, comment out the `OpenAIAdapter` construction and replace with a `NotImplementedError` stub so imports don't break:

```python
# LLM adapter — will be replaced in Task 5 with _resolve_llm()
raise NotImplementedError(
    "LLM pool wiring not yet implemented — see Task 5"
)
```

**Step 3: Fix `status` command**

Replace:
```python
print(f"Model:     {settings.llm.model}")
print(f"API:       {settings.llm.api_base}")
```
With:
```python
pool_count = len(settings.llm.pools)
print(f"Pools:     {pool_count} configured (default: {settings.llm.default_pool})")
```

**Step 4: Fix `_run_agent` banner**

Replace:
```python
console.print(f"🦑 [bold]squidbot[/bold] 0.1.0  •  model: [cyan]{settings.llm.model}[/cyan]")
```
With:
```python
console.print(f"🦑 [bold]squidbot[/bold] 0.1.0  •  pool: [cyan]{settings.llm.default_pool}[/cyan]")
```

**Step 5: Fix `_print_banner()`**

Replace:
```python
model = settings.llm.model
...
print(f"   model:     {model}", file=sys.stderr)
```
With:
```python
pool = settings.llm.default_pool
...
print(f"   pool:      {pool}", file=sys.stderr)
```

**Step 6: Fix `_run_onboard()`**

Replace the onboard wizard body with a new-format writer:

```python
async def _run_onboard(config_path: Path) -> None:
    """Interactive setup wizard."""
    print("squidbot setup wizard")
    print("=" * 40)
    api_base = input("LLM API base URL [https://openrouter.ai/api/v1]: ").strip()
    api_key = input("API key: ").strip()
    model_id = input("Model identifier [anthropic/claude-opus-4-5]: ").strip()

    from squidbot.config.schema import (  # noqa: PLC0415
        LLMModelConfig,
        LLMPoolEntry,
        LLMProviderConfig,
    )

    settings = Settings()
    settings.llm.providers["default"] = LLMProviderConfig(
        api_base=api_base or "https://openrouter.ai/api/v1",
        api_key=api_key,
    )
    settings.llm.models["default"] = LLMModelConfig(
        provider="default",
        model=model_id or "anthropic/claude-opus-4-5",
    )
    settings.llm.pools["default"] = [LLMPoolEntry(model="default")]
    settings.llm.default_pool = "default"

    settings.save(config_path)
    print(f"\nConfiguration saved to {config_path}")
    print("Run 'squidbot agent' to start chatting!")
```

**Step 7: Run ruff and mypy**

```bash
uv run ruff check . && uv run mypy squidbot/
```
Fix any issues.

**Step 8: Run tests**

```bash
uv run pytest -q
```
Expected: all tests pass (agent/gateway tests will be skipped or fail only on the `NotImplementedError` stub — that's acceptable until Task 5).

**Step 9: Commit**

```bash
git add squidbot/cli/main.py
git commit -m "fix: update cli references after LLMConfig breaking change"
```

---

## Task 3: `PooledLLMAdapter` in `adapters/llm/pool.py`

**Files:**
- Create: `squidbot/adapters/llm/pool.py`
- Create: `tests/adapters/llm/test_pool.py`

**Step 1: Write the failing tests**

```python
# tests/adapters/llm/test_pool.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from squidbot.adapters.llm.pool import PooledLLMAdapter
from squidbot.core.models import Message, ToolDefinition


def _make_adapter(chunks: list[str] | None = None, raises: Exception | None = None):
    """Build a mock LLMPort."""
    adapter = MagicMock()
    if raises is not None:
        adapter.chat = AsyncMock(side_effect=raises)
    else:
        async def _chat(*a, **kw):
            for chunk in (chunks or ["hello"]):
                yield chunk
        adapter.chat = _chat
    return adapter


async def _collect(pool, messages, tools):
    result = []
    async for chunk in await pool.chat(messages, tools):
        result.append(chunk)
    return result


@pytest.fixture
def msgs():
    return [Message(role="user", content="hi")]


@pytest.fixture
def tools():
    return []


async def test_single_adapter_delegates(msgs, tools):
    adapter = _make_adapter(["hello", " world"])
    pool = PooledLLMAdapter([adapter])
    result = await _collect(pool, msgs, tools)
    assert result == ["hello", " world"]


async def test_first_succeeds_second_never_called(msgs, tools):
    a1 = _make_adapter(["ok"])
    a2 = _make_adapter(["fallback"])
    pool = PooledLLMAdapter([a1, a2])
    result = await _collect(pool, msgs, tools)
    assert result == ["ok"]


async def test_first_fails_second_called(msgs, tools):
    a1 = _make_adapter(raises=RuntimeError("timeout"))
    a2 = _make_adapter(["fallback"])
    pool = PooledLLMAdapter([a1, a2])
    result = await _collect(pool, msgs, tools)
    assert result == ["fallback"]


async def test_auth_error_logs_warning(msgs, tools, caplog):
    import logging

    class AuthenticationError(Exception):
        pass

    a1 = _make_adapter(raises=AuthenticationError("bad key"))
    a2 = _make_adapter(["ok"])
    pool = PooledLLMAdapter([a1, a2])
    with patch("squidbot.adapters.llm.pool.logger") as mock_log:
        result = await _collect(pool, msgs, tools)
    assert result == ["ok"]
    mock_log.warning.assert_called_once()


async def test_generic_error_logs_info_not_warning(msgs, tools):
    a1 = _make_adapter(raises=RuntimeError("connection refused"))
    a2 = _make_adapter(["ok"])
    pool = PooledLLMAdapter([a1, a2])
    with patch("squidbot.adapters.llm.pool.logger") as mock_log:
        result = await _collect(pool, msgs, tools)
    assert result == ["ok"]
    mock_log.warning.assert_not_called()
    mock_log.info.assert_called_once()


async def test_all_fail_raises_last(msgs, tools):
    a1 = _make_adapter(raises=RuntimeError("first"))
    a2 = _make_adapter(raises=RuntimeError("second"))
    pool = PooledLLMAdapter([a1, a2])
    with pytest.raises(RuntimeError, match="second"):
        await _collect(pool, msgs, tools)


async def test_auth_error_detected_by_name(msgs, tools):
    """_is_auth_error checks class name, works for any provider."""
    class AuthenticationError(Exception):
        pass
    assert PooledLLMAdapter._is_auth_error(AuthenticationError("x")) is True
    assert PooledLLMAdapter._is_auth_error(RuntimeError("x")) is False
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/adapters/llm/test_pool.py -v
```
Expected: FAIL — `squidbot.adapters.llm.pool` does not exist.

**Step 3: Implement `pool.py`**

Create `squidbot/adapters/llm/pool.py`:

```python
"""
Pooled LLM adapter with sequential fallback.

Wraps an ordered list of LLMPort instances. On any exception from the active
adapter the next one is tried. AuthenticationError is additionally logged at
WARNING level so the user sees credential failures even when a fallback succeeds.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from squidbot.core.models import Message, ToolDefinition


def _is_auth_error(exc: Exception) -> bool:
    """Return True if the exception looks like an authentication failure."""
    return "AuthenticationError" in type(exc).__name__


class PooledLLMAdapter:
    """
    LLM adapter that tries a list of adapters in order.

    Implements LLMPort via structural subtyping.
    """

    def __init__(self, adapters: list[Any]) -> None:
        """
        Args:
            adapters: Ordered list of LLMPort instances. First is tried first.
        """
        if not adapters:
            raise ValueError("PooledLLMAdapter requires at least one adapter")
        self._adapters = adapters

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        """Return True if the exception looks like an authentication failure."""
        return _is_auth_error(exc)

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        *,
        stream: bool = True,
    ) -> AsyncIterator[str | list[Any]]:
        """
        Try each adapter in order, falling back on any exception.

        Args:
            messages: Full conversation history.
            tools: Available tool definitions.
            stream: Whether to stream the response.

        Raises:
            Exception: The last exception if all adapters fail.
        """
        last_exc: Exception | None = None
        for i, adapter in enumerate(self._adapters):
            try:
                async for chunk in await adapter.chat(messages, tools, stream=stream):
                    yield chunk
                return
            except Exception as exc:
                if _is_auth_error(exc):
                    logger.warning(
                        "llm pool: auth error on adapter {} ({}), trying next",
                        i,
                        type(exc).__name__,
                    )
                else:
                    logger.info(
                        "llm pool: error on adapter {} ({}), trying next",
                        i,
                        type(exc).__name__,
                    )
                last_exc = exc
        raise last_exc  # type: ignore[misc]
```

**Step 4: Run tests**

```bash
uv run pytest tests/adapters/llm/test_pool.py -v
```
Expected: all PASS.

**Step 5: ruff + mypy**

```bash
uv run ruff check . && uv run mypy squidbot/
```

**Step 6: Commit**

```bash
git add squidbot/adapters/llm/pool.py tests/adapters/llm/test_pool.py
git commit -m "feat: add PooledLLMAdapter with sequential fallback"
```

---

## Task 4: `AgentLoop.run()` gains optional `llm` override

**Files:**
- Modify: `squidbot/core/agent.py`
- Modify: `tests/core/test_agent.py`

**Step 1: Read the current `AgentLoop.run()` signature**

```bash
uv run grep -n "async def run" squidbot/core/agent.py
```

**Step 2: Write the failing test**

Add to `tests/core/test_agent.py`:

```python
async def test_run_with_llm_override():
    """llm_override replaces self._llm for a single run."""
    default_llm = ScriptedLLM([SimpleResponse("from default")])
    override_llm = ScriptedLLM([SimpleResponse("from override")])

    loop = AgentLoop(
        llm=default_llm,
        memory=MemoryManager(storage=InMemoryStorage(), max_history_messages=10, skills=NoSkills()),
        registry=ToolRegistry(),
        system_prompt="test",
    )
    channel = CollectingChannel()  # or whatever test double exists
    await loop.run(Session(channel="cli", sender_id="u1"), "hello", channel, llm=override_llm)
    assert "from override" in channel.collected_text
    assert "from default" not in channel.collected_text
```

**Step 3: Run test to verify it fails**

```bash
uv run pytest tests/core/test_agent.py::test_run_with_llm_override -v
```
Expected: FAIL — `run()` does not accept `llm` kwarg.

**Step 4: Add `llm` parameter to `AgentLoop.run()`**

In `squidbot/core/agent.py`, find `async def run(` and add:

```python
async def run(
    self,
    session: Session,
    user_message: str,
    channel: ChannelPort,
    *,
    llm: LLMPort | None = None,
) -> None:
```

Inside `run()`, replace all uses of `self._llm` with `_llm = llm or self._llm` at the top of the method, then use `_llm` throughout.

**Step 5: Run tests**

```bash
uv run pytest tests/core/test_agent.py -v
```
Expected: all PASS including new test.

**Step 6: ruff + mypy**

```bash
uv run ruff check . && uv run mypy squidbot/
```

**Step 7: Commit**

```bash
git add squidbot/core/agent.py tests/core/test_agent.py
git commit -m "feat: add optional llm override to AgentLoop.run()"
```

---

## Task 5: `_resolve_llm()` helper and full wiring in `_make_agent_loop()`

**Files:**
- Modify: `squidbot/cli/main.py`
- Create: `tests/adapters/test_llm_wiring.py`

**Step 1: Write the failing tests**

```python
# tests/adapters/test_llm_wiring.py
from __future__ import annotations

import pytest
from squidbot.cli.main import _resolve_llm
from squidbot.config.schema import (
    LLMConfig,
    LLMModelConfig,
    LLMPoolEntry,
    LLMProviderConfig,
    Settings,
)
from squidbot.adapters.llm.openai import OpenAIAdapter
from squidbot.adapters.llm.pool import PooledLLMAdapter


def _make_settings(pools: dict) -> Settings:
    s = Settings()
    s.llm = LLMConfig(
        default_pool="smart",
        providers={
            "or": LLMProviderConfig(api_base="https://api.test", api_key="sk-test"),
        },
        models={
            "opus": LLMModelConfig(provider="or", model="claude-opus"),
            "haiku": LLMModelConfig(provider="or", model="claude-haiku"),
        },
        pools=pools,
    )
    return s


def test_single_entry_pool_returns_openai_adapter():
    s = _make_settings({"smart": [LLMPoolEntry(model="opus")]})
    llm = _resolve_llm(s, "smart")
    assert isinstance(llm, OpenAIAdapter)


def test_multi_entry_pool_returns_pooled_adapter():
    s = _make_settings({
        "smart": [LLMPoolEntry(model="opus"), LLMPoolEntry(model="haiku")]
    })
    llm = _resolve_llm(s, "smart")
    assert isinstance(llm, PooledLLMAdapter)


def test_unknown_pool_raises():
    s = _make_settings({"smart": [LLMPoolEntry(model="opus")]})
    with pytest.raises(ValueError, match="pool 'missing'"):
        _resolve_llm(s, "missing")


def test_unknown_model_raises():
    s = _make_settings({"smart": [LLMPoolEntry(model="ghost")]})
    with pytest.raises(ValueError, match="model 'ghost'"):
        _resolve_llm(s, "smart")


def test_unknown_provider_raises():
    s = Settings()
    s.llm = LLMConfig(
        default_pool="smart",
        providers={},
        models={"opus": LLMModelConfig(provider="missing_provider", model="claude")},
        pools={"smart": [LLMPoolEntry(model="opus")]},
    )
    with pytest.raises(ValueError, match="provider 'missing_provider'"):
        _resolve_llm(s, "smart")
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/adapters/test_llm_wiring.py -v
```
Expected: FAIL — `_resolve_llm` not importable from `squidbot.cli.main`.

**Step 3: Implement `_resolve_llm()` in `main.py`**

Add before `_make_agent_loop()`:

```python
def _resolve_llm(settings: Settings, pool_name: str) -> LLMPort:
    """
    Build an LLMPort from a named pool in settings.

    Returns a single OpenAIAdapter if the pool has one entry,
    or a PooledLLMAdapter if it has multiple entries.

    Args:
        settings: Loaded application settings.
        pool_name: Name of the pool in settings.llm.pools.

    Raises:
        ValueError: If the pool, model, or provider is not found.
    """
    from squidbot.adapters.llm.openai import OpenAIAdapter  # noqa: PLC0415
    from squidbot.adapters.llm.pool import PooledLLMAdapter  # noqa: PLC0415

    pool_entries = settings.llm.pools.get(pool_name)
    if not pool_entries:
        raise ValueError(f"LLM pool '{pool_name}' not found in config")

    adapters: list[Any] = []
    for entry in pool_entries:
        model_cfg = settings.llm.models.get(entry.model)
        if not model_cfg:
            raise ValueError(f"LLM model '{entry.model}' not found in llm.models")
        provider_cfg = settings.llm.providers.get(model_cfg.provider)
        if not provider_cfg:
            raise ValueError(
                f"LLM provider '{model_cfg.provider}' not found in llm.providers"
            )
        adapters.append(OpenAIAdapter(
            api_base=provider_cfg.api_base,
            api_key=provider_cfg.api_key,
            model=model_cfg.model,
        ))

    if len(adapters) == 1:
        return adapters[0]
    return PooledLLMAdapter(adapters)
```

**Step 4: Wire `_resolve_llm()` into `_make_agent_loop()`**

Replace the `NotImplementedError` stub with:

```python
import functools  # noqa: PLC0415

default_pool = settings.llm.default_pool
llm = _resolve_llm(settings, default_pool)
```

Also update the `SubAgentFactory` construction (step covered in Task 6).

**Step 5: Run wiring tests**

```bash
uv run pytest tests/adapters/test_llm_wiring.py -v
```
Expected: all PASS.

**Step 6: ruff + mypy**

```bash
uv run ruff check . && uv run mypy squidbot/
```

**Step 7: Commit**

```bash
git add squidbot/cli/main.py tests/adapters/test_llm_wiring.py
git commit -m "feat: add _resolve_llm() and wire default pool in _make_agent_loop()"
```

---

## Task 6: Wire pool into `HeartbeatService`

**Files:**
- Modify: `squidbot/core/heartbeat.py`
- Modify: `squidbot/cli/main.py`
- Modify: `tests/core/test_heartbeat.py`

**Step 1: Write the failing test**

Add to `tests/core/test_heartbeat.py`:

```python
async def test_heartbeat_uses_llm_override():
    """When llm_override is set, heartbeat passes it to AgentLoop.run()."""
    calls = []

    class CapturingLoop:
        async def run(self, session, message, channel, *, llm=None):
            calls.append(llm)
            from squidbot.core.models import OutboundMessage
            await channel.send(OutboundMessage(session=session, text="HEARTBEAT_OK"))

    override_llm = object()  # sentinel
    tracker = LastChannelTracker()
    tracker.update(FakeChannel(), Session(channel="matrix", sender_id="u1"))
    svc = HeartbeatService(
        agent_loop=CapturingLoop(),  # type: ignore[arg-type]
        tracker=tracker,
        workspace=tmp_path,
        config=HeartbeatConfig(),
        llm_override=override_llm,  # type: ignore[arg-type]
    )
    await svc._tick()
    assert calls == [override_llm]


async def test_heartbeat_no_override_passes_none():
    calls = []

    class CapturingLoop:
        async def run(self, session, message, channel, *, llm=None):
            calls.append(llm)
            from squidbot.core.models import OutboundMessage
            await channel.send(OutboundMessage(session=session, text="HEARTBEAT_OK"))

    tracker = LastChannelTracker()
    tracker.update(FakeChannel(), Session(channel="matrix", sender_id="u1"))
    svc = HeartbeatService(
        agent_loop=CapturingLoop(),  # type: ignore[arg-type]
        tracker=tracker,
        workspace=tmp_path,
        config=HeartbeatConfig(),
    )
    await svc._tick()
    assert calls == [None]
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/core/test_heartbeat.py -k "llm_override" -v
```
Expected: FAIL.

**Step 3: Add `llm_override` to `HeartbeatService`**

In `squidbot/core/heartbeat.py`:

```python
def __init__(
    self,
    agent_loop: AgentLoop,
    tracker: LastChannelTracker,
    workspace: Path,
    config: HeartbeatConfig,
    llm_override: LLMPort | None = None,
) -> None:
    ...
    self._llm_override = llm_override
```

In `_tick()`, update the `agent_loop.run()` call:

```python
await self._agent_loop.run(
    self._tracker.session,
    self._config.prompt,
    sink,  # type: ignore[arg-type]
    llm=self._llm_override,
)
```

Also add `TYPE_CHECKING` import for `LLMPort`:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from squidbot.core.ports import LLMPort
```

**Step 4: Wire heartbeat pool in `_make_agent_loop()`**

In `squidbot/cli/main.py`, after building `agent_loop`:

```python
hb_pool = settings.agents.heartbeat.pool or default_pool
hb_llm = _resolve_llm(settings, hb_pool) if hb_pool != default_pool else None
```

Pass to `HeartbeatService` in `_run_gateway()`:

```python
heartbeat = HeartbeatService(
    agent_loop=agent_loop,
    tracker=tracker,
    workspace=workspace,
    config=settings.agents.heartbeat,
    llm_override=hb_llm,
)
```

Note: `hb_llm` needs to be returned from `_make_agent_loop()` or computed in `_run_gateway()`. Since heartbeat config is under `settings.agents`, compute it in `_run_gateway()` directly after calling `_make_agent_loop()`.

**Step 5: Run tests**

```bash
uv run pytest tests/core/test_heartbeat.py -v
```
Expected: all PASS.

**Step 6: ruff + mypy**

```bash
uv run ruff check . && uv run mypy squidbot/
```

**Step 7: Commit**

```bash
git add squidbot/core/heartbeat.py squidbot/cli/main.py tests/core/test_heartbeat.py
git commit -m "feat: wire llm_override into HeartbeatService for pool support"
```

---

## Task 7: Pool-aware `SubAgentFactory`

**Files:**
- Modify: `squidbot/adapters/tools/spawn.py`
- Modify: `squidbot/cli/main.py`
- Modify: `tests/adapters/tools/test_spawn.py`

**Step 1: Write the failing tests**

Add to `tests/adapters/tools/test_spawn.py`:

```python
def test_factory_uses_profile_pool():
    """build() calls resolve_llm with profile.pool when set."""
    calls = []
    def fake_resolve(pool_name: str):
        calls.append(pool_name)
        return MagicMock()

    from squidbot.config.schema import SpawnProfile
    factory = SubAgentFactory(
        memory=mock_memory(),
        registry=ToolRegistry(),
        system_prompt="test",
        profiles={"researcher": SpawnProfile(pool="smart")},
        default_pool="default",
        resolve_llm=fake_resolve,
    )
    factory.build(system_prompt_override=None, tools_filter=None, profile_name="researcher")
    assert calls == ["smart"]


def test_factory_uses_default_pool_when_no_profile_pool():
    calls = []
    def fake_resolve(pool_name: str):
        calls.append(pool_name)
        return MagicMock()

    from squidbot.config.schema import SpawnProfile
    factory = SubAgentFactory(
        memory=mock_memory(),
        registry=ToolRegistry(),
        system_prompt="test",
        profiles={"researcher": SpawnProfile(pool="")},
        default_pool="default",
        resolve_llm=fake_resolve,
    )
    factory.build(system_prompt_override=None, tools_filter=None, profile_name="researcher")
    assert calls == ["default"]


def test_factory_uses_default_pool_when_no_profile():
    calls = []
    def fake_resolve(pool_name: str):
        calls.append(pool_name)
        return MagicMock()

    factory = SubAgentFactory(
        memory=mock_memory(),
        registry=ToolRegistry(),
        system_prompt="test",
        profiles={},
        default_pool="default",
        resolve_llm=fake_resolve,
    )
    factory.build(system_prompt_override=None, tools_filter=None, profile_name=None)
    assert calls == ["default"]
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/adapters/tools/test_spawn.py -k "pool" -v
```
Expected: FAIL.

**Step 3: Update `SubAgentFactory`**

In `squidbot/adapters/tools/spawn.py`:

1. Remove `llm: LLMPort` from `__init__`, add `default_pool: str` and `resolve_llm: Callable[[str], LLMPort]`.
2. Update `build()` to accept `profile_name: str | None = None` and resolve LLM:

```python
from collections.abc import Callable  # add to imports

class SubAgentFactory:
    def __init__(
        self,
        memory: MemoryManager,
        registry: ToolRegistry,
        system_prompt: str,
        profiles: dict[str, SpawnProfile],
        default_pool: str,
        resolve_llm: Callable[[str], LLMPort],
    ) -> None:
        self._memory = memory
        self._registry = registry
        self._system_prompt = system_prompt
        self._profiles = profiles
        self._default_pool = default_pool
        self._resolve_llm = resolve_llm

    def build(
        self,
        system_prompt_override: str | None,
        tools_filter: list[str] | None,
        profile_name: str | None = None,
    ) -> AgentLoop:
        profile = self._profiles.get(profile_name) if profile_name else None
        pool = (profile.pool if profile and profile.pool else None) or self._default_pool
        llm = self._resolve_llm(pool)

        child_prompt = system_prompt_override or self._system_prompt
        child_registry = ToolRegistry()
        for tool in self._registry._tools.values():
            if tool.name in _SPAWN_TOOL_NAMES:
                continue
            if tools_filter is not None and tool.name not in tools_filter:
                continue
            child_registry.register(tool)

        return AgentLoop(
            llm=llm,
            memory=self._memory,
            registry=child_registry,
            system_prompt=child_prompt,
        )
```

3. Update `SpawnTool.execute()` to pass `profile_name` to `factory.build()`:

```python
agent_loop = self._factory.build(
    system_prompt_override=resolved_system_prompt,
    tools_filter=tools_filter,
    profile_name=profile_name,
)
```

**Step 4: Wire updated `SubAgentFactory` in `_make_agent_loop()`**

```python
import functools  # already imported

spawn_factory = SubAgentFactory(
    memory=memory,
    registry=registry,
    system_prompt=system_prompt,
    profiles=settings.tools.spawn.profiles,
    default_pool=default_pool,
    resolve_llm=functools.partial(_resolve_llm, settings),
)
```

**Step 5: Run full test suite**

```bash
uv run pytest -q
```
Expected: all PASS.

**Step 6: ruff + mypy**

```bash
uv run ruff check . && uv run mypy squidbot/
```

**Step 7: Commit**

```bash
git add squidbot/adapters/tools/spawn.py squidbot/cli/main.py tests/adapters/tools/test_spawn.py
git commit -m "feat: pool-aware SubAgentFactory for spawn profiles"
```

---

## Task 8: Config validation at startup

**Files:**
- Modify: `squidbot/config/schema.py`
- Modify: `tests/core/test_config.py`

**Step 1: Write the failing tests**

Add to `tests/core/test_config.py`:

```python
from pydantic import ValidationError
import pytest


def test_validation_unknown_default_pool():
    with pytest.raises(ValidationError, match="default_pool"):
        Settings.model_validate({
            "llm": {
                "default_pool": "missing",
                "providers": {"p": {"api_base": "http://x", "api_key": "k"}},
                "models": {"m": {"provider": "p", "model": "x"}},
                "pools": {"smart": [{"model": "m"}]},
            }
        })


def test_validation_pool_references_unknown_model():
    with pytest.raises(ValidationError, match="ghost"):
        Settings.model_validate({
            "llm": {
                "default_pool": "smart",
                "providers": {"p": {"api_base": "http://x", "api_key": "k"}},
                "models": {"m": {"provider": "p", "model": "x"}},
                "pools": {"smart": [{"model": "ghost"}]},
            }
        })


def test_validation_model_references_unknown_provider():
    with pytest.raises(ValidationError, match="no_provider"):
        Settings.model_validate({
            "llm": {
                "default_pool": "smart",
                "providers": {},
                "models": {"m": {"provider": "no_provider", "model": "x"}},
                "pools": {"smart": [{"model": "m"}]},
            }
        })


def test_validation_heartbeat_pool_unknown():
    with pytest.raises(ValidationError, match="heartbeat.*pool|pool.*heartbeat"):
        Settings.model_validate({
            "llm": {
                "default_pool": "smart",
                "providers": {"p": {"api_base": "http://x", "api_key": "k"}},
                "models": {"m": {"provider": "p", "model": "x"}},
                "pools": {"smart": [{"model": "m"}]},
            },
            "agents": {"heartbeat": {"pool": "missing"}},
        })


def test_validation_spawn_profile_pool_unknown():
    with pytest.raises(ValidationError, match="pool.*researcher|researcher.*pool"):
        Settings.model_validate({
            "llm": {
                "default_pool": "smart",
                "providers": {"p": {"api_base": "http://x", "api_key": "k"}},
                "models": {"m": {"provider": "p", "model": "x"}},
                "pools": {"smart": [{"model": "m"}]},
            },
            "tools": {"spawn": {"profiles": {"researcher": {"pool": "missing"}}}},
        })
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/core/test_config.py -k "validation" -v
```
Expected: FAIL — no validators exist yet.

**Step 3: Add `@model_validator` to `Settings`**

In `squidbot/config/schema.py`, add to `Settings`:

```python
from pydantic import model_validator  # add to imports

class Settings(BaseModel):
    ...

    @model_validator(mode="after")
    def _validate_llm_references(self) -> Settings:
        llm = self.llm
        # Only validate if any pools are configured
        if not llm.pools:
            return self

        # default_pool must exist
        if llm.default_pool and llm.default_pool not in llm.pools:
            raise ValueError(
                f"llm.default_pool '{llm.default_pool}' not found in llm.pools"
            )

        # Every pool entry's model must exist
        for pool_name, entries in llm.pools.items():
            for entry in entries:
                if entry.model not in llm.models:
                    raise ValueError(
                        f"Pool '{pool_name}' references unknown model '{entry.model}'"
                    )

        # Every model's provider must exist
        for model_name, model_cfg in llm.models.items():
            if model_cfg.provider not in llm.providers:
                raise ValueError(
                    f"Model '{model_name}' references unknown provider '{model_cfg.provider}'"
                )

        # heartbeat.pool must exist (if set)
        hb_pool = self.agents.heartbeat.pool
        if hb_pool and hb_pool not in llm.pools:
            raise ValueError(
                f"agents.heartbeat.pool '{hb_pool}' not found in llm.pools"
            )

        # spawn profile pools must exist (if set)
        for prof_name, prof in self.tools.spawn.profiles.items():
            if prof.pool and prof.pool not in llm.pools:
                raise ValueError(
                    f"tools.spawn.profiles.{prof_name}.pool '{prof.pool}' not found in llm.pools"
                )

        return self
```

**Step 4: Run tests**

```bash
uv run pytest tests/core/test_config.py -v
```
Expected: all PASS.

**Step 5: ruff + mypy**

```bash
uv run ruff check . && uv run mypy squidbot/
```

**Step 6: Run full suite**

```bash
uv run pytest -q
```

**Step 7: Commit**

```bash
git add squidbot/config/schema.py tests/core/test_config.py
git commit -m "feat: add startup validation for llm pool/model/provider references"
```

---

## Task 9: Final integration check

**Step 1: Run full test suite**

```bash
uv run pytest -q
```
Expected: all pass.

**Step 2: ruff + mypy clean**

```bash
uv run ruff check . && uv run mypy squidbot/
```
Expected: no errors.

**Step 3: Manual smoke test**

```bash
uv tool install --reinstall /home/alex/git/squidbot
squidbot status
```
Expected: shows pool count, no traceback.

**Step 4: Commit if anything was fixed**

```bash
git add -A && git commit -m "fix: post-integration cleanup"
```
(Only if there were fixes. Skip if clean.)
