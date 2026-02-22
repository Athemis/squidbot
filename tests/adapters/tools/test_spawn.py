"""Tests for the spawn tool adapter."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from squidbot.adapters.tools.spawn import CollectingChannel, JobStore, SubAgentFactory
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


def test_factory_build_returns_agent_loop():
    llm = MagicMock()
    memory = MagicMock()
    registry = _make_mock_registry(["shell"])
    factory = SubAgentFactory(
        llm=llm, memory=memory, registry=registry, system_prompt="parent prompt", profiles={}
    )
    loop = factory.build(system_prompt_override=None, tools_filter=None)
    assert isinstance(loop, AgentLoop)


def test_factory_build_excludes_spawn_tools():
    registry = _make_mock_registry(["shell", "spawn", "spawn_await"])
    factory = SubAgentFactory(
        llm=MagicMock(), memory=MagicMock(), registry=registry, system_prompt="p", profiles={}
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
        llm=MagicMock(), memory=MagicMock(), registry=registry, system_prompt="p", profiles={}
    )
    loop = factory.build(system_prompt_override=None, tools_filter=["shell"])
    defs = loop._registry.get_definitions()
    names = [d.name for d in defs]
    assert names == ["shell"]


def test_factory_build_with_system_prompt_override():
    registry = _make_mock_registry([])
    factory = SubAgentFactory(
        llm=MagicMock(),
        memory=MagicMock(),
        registry=registry,
        system_prompt="original",
        profiles={},
    )
    loop = factory.build(system_prompt_override="override prompt", tools_filter=None)
    assert loop._system_prompt == "override prompt"
