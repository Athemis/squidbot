# Spawn Tool Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement `spawn` and `spawn_await` tools enabling a parent agent to delegate tasks to parallel sub-agents, optionally selected by named profile.

**Architecture:** `adapters/tools/spawn.py` contains `SubAgentFactory`, `JobStore`, `CollectingChannel`, `SpawnTool`, and `SpawnAwaitTool`. Profiles are defined in `config/schema.py` under `tools.spawn`. Wiring happens in `cli/main.py::_make_agent_loop()`. Sub-agents are prevented from spawning further by excluding `spawn`/`spawn_await` from their registry.

**Tech Stack:** Python 3.14, asyncio, pydantic, squidbot core (`AgentLoop`, `ToolRegistry`, `MemoryManager`, `LLMPort`)

---

## Task 1: Config schema — `SpawnProfile` and `SpawnSettings`

**Files:**
- Modify: `squidbot/config/schema.py`

Add `SpawnProfile` and `SpawnSettings` models, and wire `SpawnSettings` into `ToolsConfig`.

**Step 1: Write the failing test**

In `tests/core/test_config.py` (create if it doesn't exist, otherwise add to it):

```python
def test_spawn_settings_defaults():
    from squidbot.config.schema import SpawnSettings
    s = SpawnSettings()
    assert s.enabled is False
    assert s.profiles == {}


def test_spawn_profile_fields():
    from squidbot.config.schema import SpawnProfile
    p = SpawnProfile(system_prompt="You are a coder.", tools=["shell"])
    assert p.system_prompt == "You are a coder."
    assert p.tools == ["shell"]


def test_spawn_settings_in_tools_config():
    from squidbot.config.schema import ToolsConfig
    cfg = ToolsConfig()
    assert cfg.spawn.enabled is False


def test_spawn_profile_empty_tools_means_all():
    from squidbot.config.schema import SpawnProfile
    p = SpawnProfile()
    assert p.tools == []  # empty = inherit all
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/core/test_config.py -v -k "spawn"
```

Expected: ImportError or AttributeError — `SpawnSettings` does not exist yet.

**Step 3: Add to `squidbot/config/schema.py`**

After `WebSearchConfig`, add:

```python
class SpawnProfile(BaseModel):
    """Configuration for a named sub-agent profile."""

    system_prompt: str = ""
    tools: list[str] = Field(
        default_factory=list,
        description="Tool names the sub-agent may use. Empty list means all tools.",
    )


class SpawnSettings(BaseModel):
    """Configuration for the spawn tool."""

    enabled: bool = False
    profiles: dict[str, SpawnProfile] = Field(default_factory=dict)
```

Then update `ToolsConfig`:

```python
class ToolsConfig(BaseModel):
    shell: ShellToolConfig = Field(default_factory=ShellToolConfig)
    files: ShellToolConfig = Field(default_factory=ShellToolConfig)
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)
    spawn: SpawnSettings = Field(default_factory=SpawnSettings)
```

**Step 4: Run tests**

```bash
uv run pytest tests/core/test_config.py -v -k "spawn"
```

Expected: all 4 tests PASS.

**Step 5: Lint and type-check**

```bash
uv run ruff check squidbot/config/schema.py && uv run mypy squidbot/config/schema.py
```

Expected: no errors.

**Step 6: Commit**

```bash
git add squidbot/config/schema.py tests/core/test_config.py
git commit -m "feat(config): add SpawnProfile and SpawnSettings"
```

---

## Task 2: `CollectingChannel` — internal non-streaming channel

**Files:**
- Create: `squidbot/adapters/tools/spawn.py` (skeleton + CollectingChannel only)
- Create: `tests/adapters/tools/test_spawn.py`

**Step 1: Write the failing test**

```python
"""Tests for the spawn tool adapter."""
from __future__ import annotations

import pytest

from squidbot.adapters.tools.spawn import CollectingChannel
from squidbot.core.models import OutboundMessage, Session


@pytest.fixture
def session() -> Session:
    return Session(channel="test", sender_id="user1")


async def test_collecting_channel_not_streaming():
    ch = CollectingChannel()
    assert ch.streaming is False


async def test_collecting_channel_collects_text(session):
    ch = CollectingChannel()
    msg = OutboundMessage(session=session, text="hello")
    await ch.send(msg)
    assert ch.collected_text == "hello"


async def test_collecting_channel_collects_multiple(session):
    ch = CollectingChannel()
    await ch.send(OutboundMessage(session=session, text="foo"))
    await ch.send(OutboundMessage(session=session, text="bar"))
    assert ch.collected_text == "foobar"


async def test_collecting_channel_receive_yields_nothing():
    ch = CollectingChannel()
    items = [msg async for msg in ch.receive()]
    assert items == []


async def test_collecting_channel_send_typing_is_noop(session):
    ch = CollectingChannel()
    await ch.send_typing(session.id)  # must not raise
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/adapters/tools/test_spawn.py -v
```

Expected: ImportError — module does not exist.

**Step 3: Create `squidbot/adapters/tools/spawn.py`** with module docstring + `CollectingChannel`:

```python
"""
Sub-agent spawn tool for squidbot.

Provides SpawnTool and SpawnAwaitTool, enabling a parent agent to delegate
tasks to isolated sub-agents running as concurrent asyncio Tasks.
Sub-agents are configured via named profiles in squidbot.yaml, or inherit
the parent's context when no profile is specified.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from squidbot.core.models import InboundMessage, OutboundMessage


class CollectingChannel:
    """
    Non-streaming channel used by sub-agents to collect their output.

    Sub-agents write their final response via send(); the result is
    retrieved via the collected_text property.
    """

    streaming: bool = False

    def __init__(self) -> None:
        """Initialise with empty buffer."""
        self._parts: list[str] = []

    async def send(self, message: OutboundMessage) -> None:
        """Append message text to the internal buffer."""
        self._parts.append(message.text)

    async def send_typing(self, session_id: str) -> None:
        """No-op — sub-agents do not send typing indicators."""

    def receive(self) -> AsyncIterator[InboundMessage]:
        """Return an async iterator that immediately exhausts."""
        return _empty_iter()

    @property
    def collected_text(self) -> str:
        """Return all collected text joined."""
        return "".join(self._parts)


async def _empty_iter() -> AsyncIterator[InboundMessage]:  # type: ignore[misc]
    """Async generator that yields nothing."""
    return
    yield  # makes this an async generator
```

**Step 4: Run tests**

```bash
uv run pytest tests/adapters/tools/test_spawn.py -v -k "collecting"
```

Expected: all 5 tests PASS.

**Step 5: Lint and type-check**

```bash
uv run ruff check squidbot/adapters/tools/spawn.py && uv run mypy squidbot/adapters/tools/spawn.py
```

Expected: no errors.

**Step 6: Commit**

```bash
git add squidbot/adapters/tools/spawn.py tests/adapters/tools/test_spawn.py
git commit -m "feat(spawn): add CollectingChannel skeleton"
```

---

## Task 3: `JobStore` — in-memory asyncio task registry

**Files:**
- Modify: `squidbot/adapters/tools/spawn.py`
- Modify: `tests/adapters/tools/test_spawn.py`

**Step 1: Write the failing tests**

Add to `tests/adapters/tools/test_spawn.py`:

```python
from squidbot.adapters.tools.spawn import JobStore


async def test_job_store_start_and_await():
    store = JobStore()

    async def work() -> str:
        return "result"

    store.start("job1", work())
    results = await store.await_jobs(["job1"])
    assert results == {"job1": "result"}


async def test_job_store_await_multiple():
    store = JobStore()

    async def slow() -> str:
        await asyncio.sleep(0)
        return "slow"

    async def fast() -> str:
        return "fast"

    store.start("a", fast())
    store.start("b", slow())
    results = await store.await_jobs(["a", "b"])
    assert results["a"] == "fast"
    assert results["b"] == "slow"


async def test_job_store_exception_captured():
    store = JobStore()

    async def boom() -> str:
        raise ValueError("oops")

    store.start("bad", boom())
    results = await store.await_jobs(["bad"])
    assert isinstance(results["bad"], ValueError)


async def test_job_store_unknown_job_id():
    store = JobStore()
    results = await store.await_jobs(["nonexistent"])
    assert "nonexistent" not in results or results["nonexistent"] is None


async def test_job_store_all_job_ids():
    store = JobStore()

    async def noop() -> str:
        return ""

    store.start("x", noop())
    store.start("y", noop())
    assert set(store.all_job_ids()) == {"x", "y"}
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/adapters/tools/test_spawn.py -v -k "job_store"
```

Expected: ImportError — `JobStore` not defined.

**Step 3: Add `JobStore` to `squidbot/adapters/tools/spawn.py`**

After the `CollectingChannel` class:

```python
class JobStore:
    """
    In-memory registry of background sub-agent asyncio Tasks.

    Each job is started as an asyncio.Task and stored by a caller-assigned ID.
    Results (or exceptions) are available via await_jobs().
    """

    def __init__(self) -> None:
        """Initialise with an empty task dict."""
        self._tasks: dict[str, asyncio.Task[str]] = {}

    def start(self, job_id: str, coro: Any) -> None:
        """
        Schedule a coroutine as a background asyncio Task.

        Args:
            job_id: Unique identifier for this job.
            coro: Coroutine to run.
        """
        self._tasks[job_id] = asyncio.ensure_future(coro)

    async def await_jobs(self, job_ids: list[str]) -> dict[str, str | BaseException]:
        """
        Wait for the specified jobs and return their results.

        Args:
            job_ids: Job IDs to wait for. Unknown IDs are silently omitted.

        Returns:
            Dict mapping job_id to result string or captured exception.
        """
        known = {jid: self._tasks[jid] for jid in job_ids if jid in self._tasks}
        if not known:
            return {}
        outcomes = await asyncio.gather(*known.values(), return_exceptions=True)
        return dict(zip(known.keys(), outcomes))

    def all_job_ids(self) -> list[str]:
        """Return all registered job IDs."""
        return list(self._tasks.keys())
```

**Step 4: Run tests**

```bash
uv run pytest tests/adapters/tools/test_spawn.py -v -k "job_store"
```

Expected: all 5 tests PASS.

**Step 5: Lint and type-check**

```bash
uv run ruff check squidbot/adapters/tools/spawn.py && uv run mypy squidbot/adapters/tools/spawn.py
```

**Step 6: Commit**

```bash
git add squidbot/adapters/tools/spawn.py tests/adapters/tools/test_spawn.py
git commit -m "feat(spawn): add JobStore"
```

---

## Task 4: `SubAgentFactory` — builds child AgentLoops

**Files:**
- Modify: `squidbot/adapters/tools/spawn.py`
- Modify: `tests/adapters/tools/test_spawn.py`

The factory builds a fresh `AgentLoop` for each sub-agent. It always removes `spawn` and
`spawn_await` from the child registry to prevent runaway nesting.

**Step 1: Write the failing tests**

Add to `tests/adapters/tools/test_spawn.py`:

```python
from unittest.mock import MagicMock, AsyncMock
from squidbot.adapters.tools.spawn import SubAgentFactory
from squidbot.core.registry import ToolRegistry
from squidbot.core.models import ToolResult


def _make_mock_registry(tool_names: list[str]) -> ToolRegistry:
    """Build a ToolRegistry with lightweight mock tools."""
    registry = ToolRegistry()
    for name in tool_names:
        tool = MagicMock()
        tool.name = name
        tool.description = f"Mock {name}"
        tool.parameters = {"type": "object", "properties": {}}
        tool.execute = AsyncMock(return_value=ToolResult(tool_call_id="", content="ok"))
        registry.register(tool)
    return registry


def test_factory_build_returns_agent_loop():
    from squidbot.core.agent import AgentLoop
    llm = MagicMock()
    memory = MagicMock()
    registry = _make_mock_registry(["shell"])
    factory = SubAgentFactory(
        llm=llm, memory=memory, registry=registry,
        system_prompt="parent prompt", profiles={}
    )
    loop = factory.build(system_prompt_override=None, tools_filter=None)
    assert isinstance(loop, AgentLoop)


def test_factory_build_excludes_spawn_tools():
    registry = _make_mock_registry(["shell", "spawn", "spawn_await"])
    factory = SubAgentFactory(
        llm=MagicMock(), memory=MagicMock(), registry=registry,
        system_prompt="p", profiles={}
    )
    loop = factory.build(system_prompt_override=None, tools_filter=None)
    # The child registry must not contain spawn or spawn_await
    defs = loop._registry.get_definitions()
    names = [d.name for d in defs]
    assert "spawn" not in names
    assert "spawn_await" not in names
    assert "shell" in names


def test_factory_build_with_tools_filter():
    registry = _make_mock_registry(["shell", "web_search", "read_file"])
    factory = SubAgentFactory(
        llm=MagicMock(), memory=MagicMock(), registry=registry,
        system_prompt="p", profiles={}
    )
    loop = factory.build(system_prompt_override=None, tools_filter=["shell"])
    defs = loop._registry.get_definitions()
    names = [d.name for d in defs]
    assert names == ["shell"]


def test_factory_build_with_system_prompt_override():
    from squidbot.core.agent import AgentLoop
    registry = _make_mock_registry([])
    factory = SubAgentFactory(
        llm=MagicMock(), memory=MagicMock(), registry=registry,
        system_prompt="original", profiles={}
    )
    loop = factory.build(system_prompt_override="override prompt", tools_filter=None)
    assert loop._system_prompt == "override prompt"
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/adapters/tools/test_spawn.py -v -k "factory"
```

Expected: ImportError — `SubAgentFactory` not defined.

**Step 3: Add `SubAgentFactory` to `squidbot/adapters/tools/spawn.py`**

Add imports at the top of the file (after existing imports):

```python
from squidbot.config.schema import SpawnProfile
from squidbot.core.agent import AgentLoop
from squidbot.core.memory import MemoryManager
from squidbot.core.ports import LLMPort
from squidbot.core.registry import ToolRegistry
```

Then add the class:

```python
_SPAWN_TOOL_NAMES = {"spawn", "spawn_await"}


class SubAgentFactory:
    """
    Builds fresh AgentLoop instances for sub-agents.

    Each sub-agent gets its own registry (filtered copy of the parent's)
    and optionally a different system prompt. spawn/spawn_await are always
    excluded from sub-agent registries to prevent runaway nesting.
    """

    def __init__(
        self,
        llm: LLMPort,
        memory: MemoryManager,
        registry: ToolRegistry,
        system_prompt: str,
        profiles: dict[str, SpawnProfile],
    ) -> None:
        """
        Args:
            llm: LLM adapter shared with parent.
            memory: Memory manager shared with parent.
            registry: Parent's tool registry (source for sub-agent tools).
            system_prompt: Parent's system prompt (default for sub-agents).
            profiles: Named sub-agent profiles from config.
        """
        self._llm = llm
        self._memory = memory
        self._registry = registry
        self._system_prompt = system_prompt
        self._profiles = profiles

    def build(
        self,
        system_prompt_override: str | None,
        tools_filter: list[str] | None,
    ) -> AgentLoop:
        """
        Build a fresh AgentLoop for a sub-agent.

        Args:
            system_prompt_override: If set, replaces the parent system prompt.
            tools_filter: If set, only these tool names are available.
                          spawn/spawn_await are always excluded regardless.

        Returns:
            A new AgentLoop with an isolated tool registry.
        """
        child_prompt = system_prompt_override or self._system_prompt

        child_registry = ToolRegistry()
        for tool in self._registry._tools.values():
            if tool.name in _SPAWN_TOOL_NAMES:
                continue
            if tools_filter is not None and tool.name not in tools_filter:
                continue
            child_registry.register(tool)

        return AgentLoop(
            llm=self._llm,
            memory=self._memory,
            registry=child_registry,
            system_prompt=child_prompt,
        )
```

**Step 4: Run tests**

```bash
uv run pytest tests/adapters/tools/test_spawn.py -v -k "factory"
```

Expected: all 4 tests PASS.

**Step 5: Lint and type-check**

```bash
uv run ruff check squidbot/adapters/tools/spawn.py && uv run mypy squidbot/adapters/tools/spawn.py
```

**Step 6: Commit**

```bash
git add squidbot/adapters/tools/spawn.py tests/adapters/tools/test_spawn.py
git commit -m "feat(spawn): add SubAgentFactory"
```

---

## Task 5: `SpawnTool` — non-blocking spawn with profile support

**Files:**
- Modify: `squidbot/adapters/tools/spawn.py`
- Modify: `tests/adapters/tools/test_spawn.py`

**Step 1: Write the failing tests**

Add to `tests/adapters/tools/test_spawn.py`:

```python
from squidbot.adapters.tools.spawn import SpawnTool


def _make_factory(response: str = "sub result") -> tuple[SubAgentFactory, ToolRegistry]:
    """Return a factory whose sub-agents always respond with `response`."""
    from squidbot.core.models import ToolResult

    registry = _make_mock_registry(["shell"])

    async def fake_chat(messages, tools, *, stream=True):
        yield response

    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=fake_chat)
    memory = MagicMock()
    memory.build_messages = AsyncMock(return_value=[])
    memory.persist_exchange = AsyncMock()

    factory = SubAgentFactory(
        llm=llm, memory=memory, registry=registry,
        system_prompt="parent", profiles={}
    )
    return factory, registry


async def test_spawn_tool_returns_job_id_immediately():
    factory, _ = _make_factory()
    job_store = JobStore()
    tool = SpawnTool(factory=factory, job_store=job_store)
    result = await tool.execute(task="do something")
    assert not result.is_error
    assert len(result.content) > 0  # job_id returned


async def test_spawn_tool_empty_task_is_error():
    factory, _ = _make_factory()
    job_store = JobStore()
    tool = SpawnTool(factory=factory, job_store=job_store)
    result = await tool.execute(task="")
    assert result.is_error


async def test_spawn_tool_missing_task_is_error():
    factory, _ = _make_factory()
    job_store = JobStore()
    tool = SpawnTool(factory=factory, job_store=job_store)
    result = await tool.execute()
    assert result.is_error


async def test_spawn_tool_unknown_profile_is_error():
    factory, _ = _make_factory()
    job_store = JobStore()
    tool = SpawnTool(factory=factory, job_store=job_store)
    result = await tool.execute(task="do it", profile="nonexistent")
    assert result.is_error
    assert "nonexistent" in result.content


async def test_spawn_tool_registers_job():
    factory, _ = _make_factory()
    job_store = JobStore()
    tool = SpawnTool(factory=factory, job_store=job_store)
    result = await tool.execute(task="work")
    job_id = result.content.strip()
    assert job_id in job_store.all_job_ids()


async def test_spawn_tool_profile_enum_in_definition():
    from squidbot.config.schema import SpawnProfile
    registry = _make_mock_registry([])
    profiles = {
        "coder": SpawnProfile(system_prompt="coder", tools=[]),
        "writer": SpawnProfile(system_prompt="writer", tools=[]),
    }
    factory = SubAgentFactory(
        llm=MagicMock(), memory=MagicMock(), registry=registry,
        system_prompt="p", profiles=profiles
    )
    job_store = JobStore()
    tool = SpawnTool(factory=factory, job_store=job_store)
    defn = tool.to_definition()
    profile_param = defn.parameters["properties"]["profile"]
    assert set(profile_param["enum"]) == {"coder", "writer"}


async def test_spawn_tool_no_profile_enum_when_no_profiles():
    registry = _make_mock_registry([])
    factory = SubAgentFactory(
        llm=MagicMock(), memory=MagicMock(), registry=registry,
        system_prompt="p", profiles={}
    )
    job_store = JobStore()
    tool = SpawnTool(factory=factory, job_store=job_store)
    defn = tool.to_definition()
    profile_param = defn.parameters["properties"]["profile"]
    assert "enum" not in profile_param
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/adapters/tools/test_spawn.py -v -k "spawn_tool"
```

Expected: ImportError — `SpawnTool` not defined.

**Step 3: Add `SpawnTool` to `squidbot/adapters/tools/spawn.py`**

Add at the top: `import uuid`

Then add the class after `SubAgentFactory`:

```python
class SpawnTool:
    """
    Starts a sub-agent as a background asyncio Task.

    Returns a job_id immediately without waiting for completion.
    Use spawn_await to retrieve results.
    """

    name = "spawn"
    description = (
        "Delegate a task to an isolated sub-agent running in the background. "
        "Returns a job_id immediately. Use spawn_await to collect the result. "
        "Multiple sub-agents can run in parallel."
    )

    def __init__(self, factory: SubAgentFactory, job_store: JobStore) -> None:
        """
        Args:
            factory: Builds child AgentLoop instances.
            job_store: Stores running jobs by ID.
        """
        self._factory = factory
        self._job_store = job_store

    @property
    def parameters(self) -> dict[str, Any]:
        """Build tool parameter schema dynamically (profile enum from configured profiles)."""
        profile_prop: dict[str, Any] = {
            "type": "string",
            "description": "Named sub-agent profile. Omit to inherit parent context.",
        }
        profile_names = list(self._factory._profiles.keys())
        if profile_names:
            profile_prop["enum"] = profile_names

        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task for the sub-agent to complete.",
                },
                "profile": profile_prop,
                "context": {
                    "type": "string",
                    "description": "Additional context prepended to the task.",
                },
                "system_prompt": {
                    "type": "string",
                    "description": "Override the sub-agent's system prompt.",
                },
                "tools": {
                    "type": "string",
                    "description": "Comma-separated tool whitelist. Overrides profile tools.",
                },
            },
            "required": ["task"],
        }

    def to_definition(self) -> "ToolDefinition":
        """Return a ToolDefinition with the dynamic parameter schema."""
        from squidbot.core.models import ToolDefinition  # noqa: PLC0415
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    async def execute(self, **kwargs: Any) -> "ToolResult":
        """
        Start a sub-agent task asynchronously.

        Args:
            **kwargs: task (required), profile, context, system_prompt, tools.

        Returns:
            ToolResult with job_id on success, or is_error=True on validation failure.
        """
        from squidbot.core.models import Session, ToolResult  # noqa: PLC0415

        task_raw = kwargs.get("task")
        if not isinstance(task_raw, str) or not task_raw.strip():
            return ToolResult(tool_call_id="", content="Error: task is required", is_error=True)
        task: str = task_raw.strip()

        profile_name: str | None = kwargs.get("profile") if isinstance(kwargs.get("profile"), str) else None
        context: str = kwargs.get("context") if isinstance(kwargs.get("context"), str) else ""  # type: ignore[assignment]
        system_prompt_override: str | None = kwargs.get("system_prompt") if isinstance(kwargs.get("system_prompt"), str) else None
        tools_raw: str | None = kwargs.get("tools") if isinstance(kwargs.get("tools"), str) else None

        # Resolve profile
        resolved_system_prompt = system_prompt_override
        tools_filter: list[str] | None = None

        if profile_name is not None:
            profile = self._factory._profiles.get(profile_name)
            if profile is None:
                return ToolResult(
                    tool_call_id="",
                    content=f"Error: unknown profile '{profile_name}'",
                    is_error=True,
                )
            if resolved_system_prompt is None and profile.system_prompt:
                resolved_system_prompt = profile.system_prompt
            if profile.tools:
                tools_filter = profile.tools

        # Explicit tools param overrides profile
        if tools_raw:
            tools_filter = [t.strip() for t in tools_raw.split(",") if t.strip()]

        user_message = f"{context}\n\n{task}".strip() if context else task

        job_id = uuid.uuid4().hex[:8]
        agent_loop = self._factory.build(
            system_prompt_override=resolved_system_prompt,
            tools_filter=tools_filter,
        )
        channel = CollectingChannel()
        session = Session(channel="spawn", sender_id=job_id)

        async def _run() -> str:
            await agent_loop.run(session=session, user_message=user_message, channel=channel)
            return channel.collected_text

        self._job_store.start(job_id, _run())
        return ToolResult(tool_call_id="", content=job_id)
```

**Step 4: Run tests**

```bash
uv run pytest tests/adapters/tools/test_spawn.py -v -k "spawn_tool"
```

Expected: all 8 tests PASS.

**Step 5: Lint and type-check**

```bash
uv run ruff check squidbot/adapters/tools/spawn.py && uv run mypy squidbot/adapters/tools/spawn.py
```

**Step 6: Commit**

```bash
git add squidbot/adapters/tools/spawn.py tests/adapters/tools/test_spawn.py
git commit -m "feat(spawn): add SpawnTool with profile support"
```

---

## Task 6: `SpawnAwaitTool` — collect results from background jobs

**Files:**
- Modify: `squidbot/adapters/tools/spawn.py`
- Modify: `tests/adapters/tools/test_spawn.py`

**Step 1: Write the failing tests**

Add to `tests/adapters/tools/test_spawn.py`:

```python
from squidbot.adapters.tools.spawn import SpawnAwaitTool


async def test_spawn_await_collects_result():
    factory, _ = _make_factory(response="done")
    job_store = JobStore()
    spawn = SpawnTool(factory=factory, job_store=job_store)
    await_tool = SpawnAwaitTool(job_store=job_store)

    r = await spawn.execute(task="work")
    job_id = r.content.strip()

    result = await await_tool.execute(job_ids=job_id)
    assert not result.is_error
    assert f"[{job_id}: OK]" in result.content
    assert "done" in result.content


async def test_spawn_await_wildcard_collects_all():
    factory, _ = _make_factory(response="x")
    job_store = JobStore()
    spawn = SpawnTool(factory=factory, job_store=job_store)
    await_tool = SpawnAwaitTool(job_store=job_store)

    r1 = await spawn.execute(task="task1")
    r2 = await spawn.execute(task="task2")
    id1, id2 = r1.content.strip(), r2.content.strip()

    result = await await_tool.execute(job_ids="*")
    assert f"[{id1}: OK]" in result.content
    assert f"[{id2}: OK]" in result.content


async def test_spawn_await_error_embedded_not_is_error():
    from squidbot.core.models import ToolResult

    registry = _make_mock_registry([])

    async def boom_chat(messages, tools, *, stream=True):
        raise RuntimeError("LLM down")
        yield  # make it an async generator

    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=boom_chat)
    memory = MagicMock()
    memory.build_messages = AsyncMock(return_value=[])
    memory.persist_exchange = AsyncMock()

    factory = SubAgentFactory(
        llm=llm, memory=memory, registry=registry,
        system_prompt="p", profiles={}
    )
    job_store = JobStore()
    spawn = SpawnTool(factory=factory, job_store=job_store)
    await_tool = SpawnAwaitTool(job_store=job_store)

    r = await spawn.execute(task="fail")
    job_id = r.content.strip()

    result = await await_tool.execute(job_ids=job_id)
    # is_error must be False — failures embedded in content
    assert not result.is_error
    assert f"[{job_id}: OK]" in result.content or f"[{job_id}: ERROR]" in result.content


async def test_spawn_await_unknown_job_id():
    job_store = JobStore()
    await_tool = SpawnAwaitTool(job_store=job_store)
    result = await await_tool.execute(job_ids="doesnotexist")
    assert not result.is_error
    assert "[doesnotexist: NOT FOUND]" in result.content


async def test_spawn_await_no_jobs_wildcard():
    job_store = JobStore()
    await_tool = SpawnAwaitTool(job_store=job_store)
    result = await await_tool.execute(job_ids="*")
    assert not result.is_error
    assert "No jobs" in result.content


async def test_spawn_await_missing_job_ids_is_error():
    job_store = JobStore()
    await_tool = SpawnAwaitTool(job_store=job_store)
    result = await await_tool.execute()
    assert result.is_error
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/adapters/tools/test_spawn.py -v -k "spawn_await"
```

Expected: ImportError — `SpawnAwaitTool` not defined.

**Step 3: Add `SpawnAwaitTool` to `squidbot/adapters/tools/spawn.py`**

```python
class SpawnAwaitTool:
    """
    Waits for one or more background sub-agent jobs and returns their results.

    Always returns is_error=False. Individual job failures are embedded in
    the content as [job_id: ERROR] markers so the parent sees all results.
    """

    name = "spawn_await"
    description = (
        "Wait for background sub-agent jobs to complete and retrieve their results. "
        "Pass a comma-separated list of job IDs, or '*' to wait for all pending jobs."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "job_ids": {
                "type": "string",
                "description": "Comma-separated job IDs to wait for, or '*' for all.",
            },
        },
        "required": ["job_ids"],
    }

    def __init__(self, job_store: JobStore) -> None:
        """
        Args:
            job_store: The shared job store from SpawnTool.
        """
        self._job_store = job_store

    def to_definition(self) -> "ToolDefinition":
        """Return a ToolDefinition."""
        from squidbot.core.models import ToolDefinition  # noqa: PLC0415
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    async def execute(self, **kwargs: Any) -> "ToolResult":
        """
        Wait for jobs and format results.

        Args:
            **kwargs: job_ids (required) — comma-separated IDs or '*'.

        Returns:
            ToolResult with all job results embedded. Never is_error=True
            unless job_ids is missing.
        """
        from squidbot.core.models import ToolResult  # noqa: PLC0415

        job_ids_raw = kwargs.get("job_ids")
        if not isinstance(job_ids_raw, str) or not job_ids_raw.strip():
            return ToolResult(
                tool_call_id="", content="Error: job_ids is required", is_error=True
            )

        if job_ids_raw.strip() == "*":
            ids = self._job_store.all_job_ids()
            if not ids:
                return ToolResult(tool_call_id="", content="No jobs found.")
        else:
            ids = [i.strip() for i in job_ids_raw.split(",") if i.strip()]

        results = await self._job_store.await_jobs(ids)

        parts: list[str] = []
        # Include NOT FOUND for any requested IDs that weren't in the store
        for jid in ids:
            if jid not in results:
                parts.append(f"[{jid}: NOT FOUND]")

        for jid, outcome in results.items():
            if isinstance(outcome, BaseException):
                parts.append(f"[{jid}: ERROR]\n{outcome}")
            else:
                parts.append(f"[{jid}: OK]\n{outcome}")

        return ToolResult(tool_call_id="", content="\n\n".join(parts))
```

**Step 4: Run tests**

```bash
uv run pytest tests/adapters/tools/test_spawn.py -v -k "spawn_await"
```

Expected: all 6 tests PASS.

**Step 5: Run full test file**

```bash
uv run pytest tests/adapters/tools/test_spawn.py -v
```

Expected: all tests PASS.

**Step 6: Lint and type-check**

```bash
uv run ruff check squidbot/adapters/tools/spawn.py && uv run mypy squidbot/adapters/tools/spawn.py
```

**Step 7: Commit**

```bash
git add squidbot/adapters/tools/spawn.py tests/adapters/tools/test_spawn.py
git commit -m "feat(spawn): add SpawnAwaitTool"
```

---

## Task 7: Wiring in `_make_agent_loop()` + profile system-prompt injection

**Files:**
- Modify: `squidbot/cli/main.py`
- Create: `tests/adapters/test_spawn_wiring.py`

**Step 1: Write the failing tests**

```python
"""Tests for spawn tool wiring in _make_agent_loop."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

import pytest


@pytest.fixture
def settings_with_spawn():
    from squidbot.config.schema import Settings, SpawnProfile
    s = Settings()
    s.tools.spawn.enabled = True
    s.tools.spawn.profiles = {
        "coder": SpawnProfile(system_prompt="You are a coder.", tools=["shell"]),
    }
    return s


@pytest.fixture
def settings_spawn_disabled():
    from squidbot.config.schema import Settings
    s = Settings()
    s.tools.spawn.enabled = False
    return s


async def test_spawn_tools_registered_when_enabled(settings_with_spawn, tmp_path):
    with patch("squidbot.adapters.llm.openai.AsyncOpenAI"), \
         patch.object(Path, "exists", return_value=False):
        from squidbot.cli.main import _make_agent_loop
        loop, conns = await _make_agent_loop(
            settings_with_spawn,
            storage_dir=tmp_path,
        )
    names = [d.name for d in loop._registry.get_definitions()]
    assert "spawn" in names
    assert "spawn_await" in names


async def test_spawn_tools_not_registered_when_disabled(settings_spawn_disabled, tmp_path):
    with patch("squidbot.adapters.llm.openai.AsyncOpenAI"), \
         patch.object(Path, "exists", return_value=False):
        from squidbot.cli.main import _make_agent_loop
        loop, conns = await _make_agent_loop(
            settings_spawn_disabled,
            storage_dir=tmp_path,
        )
    names = [d.name for d in loop._registry.get_definitions()]
    assert "spawn" not in names
    assert "spawn_await" not in names


async def test_profile_injected_in_system_prompt(settings_with_spawn, tmp_path):
    with patch("squidbot.adapters.llm.openai.AsyncOpenAI"), \
         patch.object(Path, "exists", return_value=False):
        from squidbot.cli.main import _make_agent_loop
        loop, _ = await _make_agent_loop(settings_with_spawn, storage_dir=tmp_path)
    assert "coder" in loop._system_prompt
    assert "<available_spawn_profiles>" in loop._system_prompt


async def test_no_profile_injection_when_no_profiles(tmp_path):
    from squidbot.config.schema import Settings
    s = Settings()
    s.tools.spawn.enabled = True
    # no profiles
    with patch("squidbot.adapters.llm.openai.AsyncOpenAI"), \
         patch.object(Path, "exists", return_value=False):
        from squidbot.cli.main import _make_agent_loop
        loop, _ = await _make_agent_loop(s, storage_dir=tmp_path)
    assert "<available_spawn_profiles>" not in loop._system_prompt
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/adapters/test_spawn_wiring.py -v
```

Note: `_make_agent_loop` currently takes only `settings` — the tests pass `storage_dir` as
a second argument (to avoid writing to `~/.squidbot` in tests). This will fail until we
refactor `_make_agent_loop` in the next step.

**Step 3: Refactor `_make_agent_loop` to accept `storage_dir`**

In `squidbot/cli/main.py`, change the signature of `_make_agent_loop`:

```python
async def _make_agent_loop(
    settings: Settings,
    storage_dir: Path | None = None,
) -> tuple[AgentLoop, list[McpConnectionProtocol]]:
```

Inside the function, replace:

```python
storage_dir = Path.home() / ".squidbot"
```

with:

```python
_storage_dir = storage_dir or Path.home() / ".squidbot"
```

And use `_storage_dir` everywhere `storage_dir` was used inside the function.

**Step 4: Add spawn wiring to `_make_agent_loop`**

After the system prompt is loaded (just before `agent_loop = AgentLoop(...)`), add:

```python
    # Spawn tool profile injection into system prompt
    if settings.tools.spawn.enabled and settings.tools.spawn.profiles:
        profile_lines = []
        for pname, prof in settings.tools.spawn.profiles.items():
            tools_str = ", ".join(prof.tools) if prof.tools else "all"
            profile_lines.append(
                f'  <profile name="{pname}">{prof.system_prompt} Tools: {tools_str}.</profile>'
            )
        profiles_xml = (
            "<available_spawn_profiles>\n"
            + "\n".join(profile_lines)
            + "\n</available_spawn_profiles>"
        )
        system_prompt = system_prompt + "\n\n" + profiles_xml
```

After `agent_loop = AgentLoop(...)`, add:

```python
    if settings.tools.spawn.enabled:
        from squidbot.adapters.tools.spawn import (  # noqa: PLC0415
            JobStore,
            SpawnAwaitTool,
            SpawnTool,
            SubAgentFactory,
        )

        spawn_factory = SubAgentFactory(
            llm=llm,
            memory=memory,
            registry=registry,
            system_prompt=system_prompt,
            profiles=settings.tools.spawn.profiles,
        )
        job_store = JobStore()
        registry.register(SpawnTool(factory=spawn_factory, job_store=job_store))
        registry.register(SpawnAwaitTool(job_store=job_store))
```

**Step 5: Run tests**

```bash
uv run pytest tests/adapters/test_spawn_wiring.py -v
```

Expected: all 4 tests PASS.

**Step 6: Run full test suite**

```bash
uv run pytest -q
```

Expected: all tests PASS (no regressions).

**Step 7: Lint and type-check**

```bash
uv run ruff check squidbot/cli/main.py squidbot/adapters/tools/spawn.py && uv run mypy squidbot/
```

**Step 8: Commit**

```bash
git add squidbot/cli/main.py squidbot/adapters/tools/spawn.py tests/adapters/test_spawn_wiring.py
git commit -m "feat(spawn): wire SpawnTool into agent loop with profile injection"
```

---

## Task 8: Final verification

**Step 1: Run full test suite**

```bash
uv run pytest -q
```

Expected: all tests PASS, 0 failures.

**Step 2: Full lint + type-check**

```bash
uv run ruff check . && uv run mypy squidbot/
```

Expected: no errors.

**Step 3: Verify spawn tool appears in tool listing**

```python
# Quick sanity check (paste into a Python REPL, no network needed)
from squidbot.config.schema import Settings, SpawnProfile
from squidbot.adapters.tools.spawn import SubAgentFactory, SpawnTool, JobStore
from squidbot.core.registry import ToolRegistry
from unittest.mock import MagicMock

registry = ToolRegistry()
profiles = {"researcher": SpawnProfile(system_prompt="Research.", tools=["web_search"])}
factory = SubAgentFactory(
    llm=MagicMock(), memory=MagicMock(), registry=registry,
    system_prompt="parent", profiles=profiles
)
tool = SpawnTool(factory=factory, job_store=JobStore())
defn = tool.to_definition()
print(defn.parameters["properties"]["profile"]["enum"])  # ["researcher"]
```

**Step 4: Commit (if any cleanup needed)**

```bash
git add -u && git commit -m "chore(spawn): final cleanup"
```
