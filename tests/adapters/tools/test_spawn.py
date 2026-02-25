"""Tests for the spawn tool adapter."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from squidbot.adapters.tools.spawn import (
    CollectingChannel,
    JobStore,
    SpawnAwaitTool,
    SpawnTool,
    SubAgentFactory,
)
from squidbot.config.schema import SpawnProfile
from squidbot.core.agent import AgentLoop
from squidbot.core.models import OutboundMessage, Session, ToolResult
from squidbot.core.registry import ToolRegistry


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
    assert results == {}


async def test_job_store_all_job_ids():
    store = JobStore()

    async def noop() -> str:
        return ""

    store.start("x", noop())
    store.start("y", noop())
    assert set(store.all_job_ids()) == {"x", "y"}


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


def test_factory_build_returns_agent_loop(tmp_path):
    llm = MagicMock()
    memory = MagicMock()
    registry = _make_mock_registry(["shell"])
    factory = SubAgentFactory(
        memory=memory,
        registry=registry,
        workspace=tmp_path,
        default_bootstrap_files=[],
        profiles={},
        default_pool="default",
        resolve_llm=lambda _: llm,
    )
    loop = factory.build(system_prompt_override=None, tools_filter=None)
    assert isinstance(loop, AgentLoop)


def test_factory_build_excludes_spawn_tools(tmp_path):
    llm = MagicMock()
    registry = _make_mock_registry(["shell", "spawn", "spawn_await"])
    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=registry,
        workspace=tmp_path,
        default_bootstrap_files=[],
        profiles={},
        default_pool="default",
        resolve_llm=lambda _: llm,
    )
    loop = factory.build(system_prompt_override=None, tools_filter=None)
    # The child registry must not contain spawn or spawn_await
    defs = loop._registry.get_definitions()
    names = [d.name for d in defs]
    assert "spawn" not in names
    assert "spawn_await" not in names
    assert "shell" in names


def test_factory_build_with_tools_filter(tmp_path):
    llm = MagicMock()
    registry = _make_mock_registry(["shell", "web_search", "read_file"])
    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=registry,
        workspace=tmp_path,
        default_bootstrap_files=[],
        profiles={},
        default_pool="default",
        resolve_llm=lambda _: llm,
    )
    loop = factory.build(system_prompt_override=None, tools_filter=["shell"])
    defs = loop._registry.get_definitions()
    names = [d.name for d in defs]
    assert names == ["shell"]


def test_factory_build_with_inline_system_prompt_only(tmp_path):
    llm = MagicMock()
    registry = _make_mock_registry([])
    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=registry,
        workspace=tmp_path,
        default_bootstrap_files=[],
        profiles={},
        default_pool="default",
        resolve_llm=lambda _: llm,
    )
    loop = factory.build(system_prompt_override="override prompt", tools_filter=None)
    assert loop._system_prompt == "override prompt"


def test_factory_build_inline_appended_to_bootstrap(tmp_path):
    (tmp_path / "AGENTS.md").write_text("bootstrap content")
    llm = MagicMock()
    registry = _make_mock_registry([])
    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=registry,
        workspace=tmp_path,
        default_bootstrap_files=["AGENTS.md"],
        profiles={},
        default_pool="default",
        resolve_llm=lambda _: llm,
    )
    loop = factory.build(system_prompt_override="override prompt", tools_filter=None)
    assert "bootstrap content" in loop._system_prompt
    assert "override prompt" in loop._system_prompt


def _make_factory(
    response: str = "sub result", tmp_path: Path | None = None
) -> tuple[SubAgentFactory, ToolRegistry]:
    """Return a factory whose sub-agents always respond with `response`."""
    registry = _make_mock_registry(["shell"])

    async def _gen() -> AsyncIterator[str]:
        yield response

    async def fake_chat(
        messages: object, tools: object, *, stream: bool = True
    ) -> AsyncIterator[str]:
        return _gen()

    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=fake_chat)
    memory = MagicMock()
    memory.build_messages = AsyncMock(return_value=[])
    memory.persist_exchange = AsyncMock()

    if tmp_path is None:
        raise ValueError("tmp_path is required; pass pytest's tmp_path fixture")
    factory = SubAgentFactory(
        memory=memory,
        registry=registry,
        workspace=tmp_path,
        default_bootstrap_files=[],
        profiles={},
        default_pool="default",
        resolve_llm=lambda _: llm,
    )
    return factory, registry


async def test_spawn_tool_returns_job_id_immediately(tmp_path):
    factory, _ = _make_factory(tmp_path=tmp_path)
    job_store = JobStore()
    tool = SpawnTool(factory=factory, job_store=job_store)
    result = await tool.execute(task="do something")
    assert not result.is_error
    assert len(result.content) > 0  # job_id returned


async def test_spawn_tool_empty_task_is_error(tmp_path):
    factory, _ = _make_factory(tmp_path=tmp_path)
    job_store = JobStore()
    tool = SpawnTool(factory=factory, job_store=job_store)
    result = await tool.execute(task="")
    assert result.is_error


async def test_spawn_tool_missing_task_is_error(tmp_path):
    factory, _ = _make_factory(tmp_path=tmp_path)
    job_store = JobStore()
    tool = SpawnTool(factory=factory, job_store=job_store)
    result = await tool.execute()
    assert result.is_error


async def test_spawn_tool_unknown_profile_is_error(tmp_path):
    factory, _ = _make_factory(tmp_path=tmp_path)
    job_store = JobStore()
    tool = SpawnTool(factory=factory, job_store=job_store)
    result = await tool.execute(task="do it", profile="nonexistent")
    assert result.is_error
    assert "nonexistent" in result.content


async def test_spawn_tool_registers_job(tmp_path):
    factory, _ = _make_factory(tmp_path=tmp_path)
    job_store = JobStore()
    tool = SpawnTool(factory=factory, job_store=job_store)
    result = await tool.execute(task="work")
    job_id = result.content.strip()
    assert job_id in job_store.all_job_ids()


async def test_spawn_tool_profile_enum_in_definition(tmp_path):
    llm = MagicMock()
    registry = _make_mock_registry([])
    profiles = {
        "coder": SpawnProfile(system_prompt="coder", tools=[]),
        "writer": SpawnProfile(system_prompt="writer", tools=[]),
    }
    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=registry,
        workspace=tmp_path,
        default_bootstrap_files=[],
        profiles=profiles,
        default_pool="default",
        resolve_llm=lambda _: llm,
    )
    job_store = JobStore()
    tool = SpawnTool(factory=factory, job_store=job_store)
    defn = tool.to_definition()
    profile_param = defn.parameters["properties"]["profile"]
    assert set(profile_param["enum"]) == {"coder", "writer"}


async def test_spawn_tool_no_profile_enum_when_no_profiles(tmp_path):
    llm = MagicMock()
    registry = _make_mock_registry([])
    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=registry,
        workspace=tmp_path,
        default_bootstrap_files=[],
        profiles={},
        default_pool="default",
        resolve_llm=lambda _: llm,
    )
    job_store = JobStore()
    tool = SpawnTool(factory=factory, job_store=job_store)
    defn = tool.to_definition()
    profile_param = defn.parameters["properties"]["profile"]
    assert "enum" not in profile_param


async def test_spawn_await_collects_result(tmp_path):
    factory, _ = _make_factory(response="done", tmp_path=tmp_path)
    job_store = JobStore()
    spawn = SpawnTool(factory=factory, job_store=job_store)
    await_tool = SpawnAwaitTool(job_store=job_store)

    r = await spawn.execute(task="work")
    job_id = r.content.strip()

    result = await await_tool.execute(job_ids=job_id)
    assert not result.is_error
    assert f"[{job_id}: OK]" in result.content
    assert "done" in result.content


async def test_spawn_await_wildcard_collects_all(tmp_path):
    factory, _ = _make_factory(response="x", tmp_path=tmp_path)
    job_store = JobStore()
    spawn = SpawnTool(factory=factory, job_store=job_store)
    await_tool = SpawnAwaitTool(job_store=job_store)

    r1 = await spawn.execute(task="task1")
    r2 = await spawn.execute(task="task2")
    id1, id2 = r1.content.strip(), r2.content.strip()

    result = await await_tool.execute(job_ids="*")
    assert f"[{id1}: OK]" in result.content
    assert f"[{id2}: OK]" in result.content


async def test_spawn_await_error_embedded_not_is_error(tmp_path):
    registry = _make_mock_registry([])

    async def boom_chat(
        messages: object, tools: object, *, stream: bool = True
    ) -> AsyncIterator[str]:
        raise RuntimeError("LLM down")
        yield  # make it an async generator

    llm = MagicMock()
    llm.chat = MagicMock(side_effect=boom_chat)
    memory = MagicMock()
    memory.build_messages = AsyncMock(return_value=[])
    memory.persist_exchange = AsyncMock()

    factory = SubAgentFactory(
        memory=memory,
        registry=registry,
        workspace=tmp_path,
        default_bootstrap_files=[],
        profiles={},
        default_pool="default",
        resolve_llm=lambda _: llm,
    )
    job_store = JobStore()
    spawn = SpawnTool(factory=factory, job_store=job_store)
    await_tool = SpawnAwaitTool(job_store=job_store)

    r = await spawn.execute(task="fail")
    job_id = r.content.strip()

    result = await await_tool.execute(job_ids=job_id)
    # is_error must be False — failures embedded in content
    assert not result.is_error
    # AgentLoop catches LLM exceptions and formats them as user-facing error text,
    # so _run() still returns a string (OK), not an exception (ERROR).
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


def test_factory_uses_profile_pool(tmp_path):
    """build() calls resolve_llm with profile.pool when set."""
    calls: list[str] = []

    def fake_resolve(pool_name: str) -> MagicMock:
        calls.append(pool_name)
        return MagicMock()

    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=ToolRegistry(),
        workspace=tmp_path,
        default_bootstrap_files=[],
        profiles={"researcher": SpawnProfile(pool="smart")},
        default_pool="default",
        resolve_llm=fake_resolve,
    )
    factory.build(system_prompt_override=None, tools_filter=None, profile_name="researcher")
    assert calls == ["smart"]


def test_factory_uses_default_pool_when_profile_has_no_pool(tmp_path):
    calls: list[str] = []

    def fake_resolve(pool_name: str) -> MagicMock:
        calls.append(pool_name)
        return MagicMock()

    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=ToolRegistry(),
        workspace=tmp_path,
        default_bootstrap_files=[],
        profiles={"researcher": SpawnProfile(pool="")},
        default_pool="default",
        resolve_llm=fake_resolve,
    )
    factory.build(system_prompt_override=None, tools_filter=None, profile_name="researcher")
    assert calls == ["default"]


def test_factory_uses_default_pool_when_no_profile(tmp_path):
    calls: list[str] = []

    def fake_resolve(pool_name: str) -> MagicMock:
        calls.append(pool_name)
        return MagicMock()

    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=ToolRegistry(),
        workspace=tmp_path,
        default_bootstrap_files=[],
        profiles={},
        default_pool="default",
        resolve_llm=fake_resolve,
    )
    factory.build(system_prompt_override=None, tools_filter=None, profile_name=None)
    assert calls == ["default"]


def test_subagent_uses_default_bootstrap_files(tmp_path):
    """No profile → loads AGENTS.md + ENVIRONMENT.md from workspace."""
    (tmp_path / "AGENTS.md").write_text("agents instructions")
    (tmp_path / "ENVIRONMENT.md").write_text("env notes")

    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=MagicMock(_tools={}),
        workspace=tmp_path,
        default_bootstrap_files=["AGENTS.md", "ENVIRONMENT.md"],
        profiles={},
        default_pool="default",
        resolve_llm=MagicMock(return_value=MagicMock()),
    )
    loop = factory.build(system_prompt_override=None, tools_filter=None)
    assert "agents instructions" in loop._system_prompt
    assert "env notes" in loop._system_prompt


def test_subagent_profile_bootstrap_files_override(tmp_path):
    """profile.bootstrap_files replaces default allowlist."""
    (tmp_path / "SOUL.md").write_text("soul content")
    (tmp_path / "AGENTS.md").write_text("agents")

    profile = SpawnProfile(bootstrap_files=["SOUL.md"])
    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=MagicMock(_tools={}),
        workspace=tmp_path,
        default_bootstrap_files=["AGENTS.md", "ENVIRONMENT.md"],
        profiles={"custom": profile},
        default_pool="default",
        resolve_llm=MagicMock(return_value=MagicMock()),
    )
    loop = factory.build(system_prompt_override=None, tools_filter=None, profile_name="custom")
    assert "soul content" in loop._system_prompt
    assert "agents" not in loop._system_prompt


def test_subagent_profile_system_prompt_file(tmp_path):
    """profile.system_prompt_file is loaded and appended."""
    (tmp_path / "AGENTS.md").write_text("agents")
    (tmp_path / "RESEARCHER.md").write_text("researcher instructions")

    profile = SpawnProfile(system_prompt_file="RESEARCHER.md")
    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=MagicMock(_tools={}),
        workspace=tmp_path,
        default_bootstrap_files=["AGENTS.md", "ENVIRONMENT.md"],
        profiles={"researcher": profile},
        default_pool="default",
        resolve_llm=MagicMock(return_value=MagicMock()),
    )
    loop = factory.build(system_prompt_override=None, tools_filter=None, profile_name="researcher")
    assert "agents" in loop._system_prompt
    assert "researcher instructions" in loop._system_prompt


def test_subagent_prompt_files_cached_when_unchanged(tmp_path, monkeypatch):
    agents_file = tmp_path / "AGENTS.md"
    profile_file = tmp_path / "RESEARCHER.md"
    agents_file.write_text("agents")
    profile_file.write_text("researcher instructions")

    profile = SpawnProfile(system_prompt_file="RESEARCHER.md")
    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=MagicMock(_tools={}),
        workspace=tmp_path,
        default_bootstrap_files=["AGENTS.md"],
        profiles={"researcher": profile},
        default_pool="default",
        resolve_llm=MagicMock(return_value=MagicMock()),
    )

    read_counts: dict[Path, int] = {agents_file: 0, profile_file: 0}
    original_read_text = Path.read_text

    def counted_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self in read_counts:
            read_counts[self] += 1
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted_read_text)

    factory.build(system_prompt_override=None, tools_filter=None, profile_name="researcher")
    factory.build(system_prompt_override=None, tools_filter=None, profile_name="researcher")

    assert read_counts[agents_file] == 1
    assert read_counts[profile_file] == 1


def test_subagent_prompt_cache_invalidates_when_file_changes(tmp_path, monkeypatch):
    agents_file = tmp_path / "AGENTS.md"
    profile_file = tmp_path / "RESEARCHER.md"
    agents_file.write_text("agents")
    profile_file.write_text("researcher instructions")

    profile = SpawnProfile(system_prompt_file="RESEARCHER.md")
    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=MagicMock(_tools={}),
        workspace=tmp_path,
        default_bootstrap_files=["AGENTS.md"],
        profiles={"researcher": profile},
        default_pool="default",
        resolve_llm=MagicMock(return_value=MagicMock()),
    )

    read_counts: dict[Path, int] = {agents_file: 0, profile_file: 0}
    original_read_text = Path.read_text

    def counted_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self in read_counts:
            read_counts[self] += 1
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted_read_text)

    factory.build(system_prompt_override=None, tools_filter=None, profile_name="researcher")
    os.utime(
        agents_file,
        ns=(agents_file.stat().st_atime_ns, agents_file.stat().st_mtime_ns + 1_000_000_000),
    )
    os.utime(
        profile_file,
        ns=(profile_file.stat().st_atime_ns, profile_file.stat().st_mtime_ns + 1_000_000_000),
    )
    factory.build(system_prompt_override=None, tools_filter=None, profile_name="researcher")

    assert read_counts[agents_file] == 2
    assert read_counts[profile_file] == 2


def test_subagent_missing_prompt_files_do_not_error_and_not_cached(tmp_path):
    profile = SpawnProfile(system_prompt_file="MISSING.md")
    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=MagicMock(_tools={}),
        workspace=tmp_path,
        default_bootstrap_files=["ALSO_MISSING.md"],
        profiles={"researcher": profile},
        default_pool="default",
        resolve_llm=MagicMock(return_value=MagicMock()),
    )

    loop = factory.build(system_prompt_override=None, tools_filter=None, profile_name="researcher")

    assert loop._system_prompt == "You are a helpful personal AI assistant."
    assert factory._system_prompt_file_cache == {}


def test_subagent_profile_all_combined(tmp_path):
    """bootstrap_files + system_prompt_file + system_prompt all combined."""
    (tmp_path / "SOUL.md").write_text("soul")
    (tmp_path / "EXTRA.md").write_text("extra file")

    profile = SpawnProfile(
        bootstrap_files=["SOUL.md"],
        system_prompt_file="EXTRA.md",
        system_prompt="inline instructions",
    )
    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=MagicMock(_tools={}),
        workspace=tmp_path,
        default_bootstrap_files=["AGENTS.md", "ENVIRONMENT.md"],
        profiles={"combo": profile},
        default_pool="default",
        resolve_llm=MagicMock(return_value=MagicMock()),
    )
    loop = factory.build(system_prompt_override=None, tools_filter=None, profile_name="combo")
    assert "soul" in loop._system_prompt
    assert "extra file" in loop._system_prompt
    assert "inline instructions" in loop._system_prompt
