"""
Tests for the agent loop using mock ports.

All external dependencies (LLM, channels, storage) are replaced with
in-memory test doubles. No network calls, no filesystem I/O.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from squidbot.core.agent import AgentLoop
from squidbot.core.memory import MemoryManager
from squidbot.core.models import (
    Message,
    OutboundMessage,
    Session,
    ToolCall,
    ToolResult,
)
from squidbot.core.registry import ToolRegistry


class ScriptedLLM:
    """LLM test double that returns pre-defined responses."""

    def __init__(self, responses: list):
        self._responses = iter(responses)

    async def chat(self, messages, tools, *, stream=True) -> AsyncIterator:
        response = next(self._responses)

        async def _gen():
            yield response

        return _gen()


class InMemoryStorage:
    def __init__(self):
        self._histories: dict[str, list[Message]] = {}
        self._global_memory: str = ""
        self._summaries: dict[str, str] = {}
        self._cursors: dict[str, int] = {}

    async def load_history(self, session_id):
        return list(self._histories.get(session_id, []))

    async def append_message(self, session_id, message):
        self._histories.setdefault(session_id, []).append(message)

    async def load_global_memory(self) -> str:
        """Load the global cross-session memory document."""
        return self._global_memory

    async def save_global_memory(self, content: str) -> None:
        """Overwrite the global memory document."""
        self._global_memory = content

    async def load_session_summary(self, session_id: str) -> str:
        """Load the auto-generated consolidation summary for this session."""
        return self._summaries.get(session_id, "")

    async def save_session_summary(self, session_id: str, content: str) -> None:
        """Overwrite the session consolidation summary."""
        self._summaries[session_id] = content

    async def load_consolidated_cursor(self, session_id: str) -> int:
        return self._cursors.get(session_id, 0)

    async def save_consolidated_cursor(self, session_id: str, cursor: int) -> None:
        self._cursors[session_id] = cursor

    async def load_cron_jobs(self):
        return []

    async def save_cron_jobs(self, jobs):
        pass


class CollectingChannel:
    """Channel test double that collects sent messages. streaming=False."""

    streaming = False

    def __init__(self):
        self.sent: list[str] = []

    async def send(self, message: OutboundMessage) -> None:
        self.sent.append(message.text)

    async def send_typing(self, session_id: str) -> None:
        pass


class StreamingChannel(CollectingChannel):
    """Channel test double with streaming=True."""

    streaming = True


class EchoTool:
    name = "echo"
    description = "Echoes text"
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, text: str, **_) -> ToolResult:
        return ToolResult(tool_call_id="", content=f"echoed: {text}")


SESSION = Session(channel="cli", sender_id="local")


@pytest.fixture
def storage():
    return InMemoryStorage()


@pytest.fixture
def memory(storage):
    return MemoryManager(storage=storage)


async def test_simple_text_response(storage, memory):
    llm = ScriptedLLM(["Hello from the bot!"])
    channel = CollectingChannel()
    loop = AgentLoop(
        llm=llm,
        memory=memory,
        registry=ToolRegistry(),
        system_prompt="You are a bot.",
    )
    await loop.run(SESSION, "Hello!", channel)
    assert channel.sent == ["Hello from the bot!"]


async def test_streaming_channel_receives_chunks(storage, memory):
    """Streaming channels get chunks sent per-chunk."""
    llm = ScriptedLLM(["chunk one"])
    channel = StreamingChannel()
    loop = AgentLoop(
        llm=llm, memory=memory, registry=ToolRegistry(), system_prompt="You are a bot."
    )
    await loop.run(SESSION, "Hello!", channel)
    assert len(channel.sent) >= 1


async def test_tool_call_then_text(storage, memory):
    tool_call = ToolCall(id="tc_1", name="echo", arguments={"text": "world"})
    llm = ScriptedLLM([[tool_call], "Result received!"])
    registry = ToolRegistry()
    registry.register(EchoTool())
    channel = CollectingChannel()
    loop = AgentLoop(llm=llm, memory=memory, registry=registry, system_prompt="You are a bot.")
    await loop.run(SESSION, "Please echo world", channel)
    assert any("Result received!" in s for s in channel.sent)


async def test_history_persisted_after_run(storage, memory):
    llm = ScriptedLLM(["I remember you."])
    channel = CollectingChannel()
    loop = AgentLoop(
        llm=llm, memory=memory, registry=ToolRegistry(), system_prompt="You are a bot."
    )
    await loop.run(SESSION, "Remember me!", channel)
    history = await storage.load_history(SESSION.id)
    assert len(history) == 2  # user + assistant
    assert history[0].role == "user"
    assert history[1].role == "assistant"


async def test_run_with_llm_override(storage, memory):
    """llm_override replaces self._llm for a single run."""
    default_llm = ScriptedLLM(["from default"])
    override_llm = ScriptedLLM(["from override"])

    loop = AgentLoop(
        llm=default_llm,
        memory=memory,
        registry=ToolRegistry(),
        system_prompt="test",
    )
    channel = CollectingChannel()
    session = Session(channel="cli", sender_id="u1")
    await loop.run(session, "hello", channel, llm=override_llm)
    assert channel.sent == ["from override"]
    # default_llm should NOT have been called (its iterator is still fresh)
    assert list(default_llm._responses) == ["from default"]


async def test_extra_tool_callable_via_run(storage, memory):
    """A tool passed via extra_tools is callable in this run."""
    tool_call = ToolCall(id="tc_1", name="echo", arguments={"text": "via extra"})
    llm = ScriptedLLM([[tool_call], "done"])
    channel = CollectingChannel()

    loop = AgentLoop(
        llm=llm,
        memory=memory,
        registry=ToolRegistry(),  # empty registry — echo not registered
        system_prompt="test",
    )
    await loop.run(SESSION, "go", channel, extra_tools=[EchoTool()])
    assert any("done" in s for s in channel.sent)


async def test_extra_tool_does_not_pollute_registry(storage, memory):
    """extra_tools from one run are not available in the next run."""
    loop = AgentLoop(
        llm=ScriptedLLM(["ok", "ok"]),
        memory=memory,
        registry=ToolRegistry(),
        system_prompt="test",
    )
    channel = CollectingChannel()
    await loop.run(SESSION, "first", channel, extra_tools=[EchoTool()])
    # Second run without extra_tools: registry still empty
    definitions = loop._registry.get_definitions()
    assert not any(d.name == "echo" for d in definitions)


async def test_tool_events_written_to_storage_after_tool_call(storage, memory):
    """After a tool call, tool_call and tool_result messages are in storage."""
    tool_call = ToolCall(id="tc_1", name="echo", arguments={"text": "hello"})
    llm = ScriptedLLM([[tool_call], "Done."])
    registry = ToolRegistry()
    registry.register(EchoTool())
    channel = CollectingChannel()
    loop = AgentLoop(llm=llm, memory=memory, registry=registry, system_prompt="sys")

    await loop.run(SESSION, "run echo", channel)

    history = await storage.load_history(SESSION.id)
    roles = [m.role for m in history]
    assert "tool_call" in roles
    assert "tool_result" in roles


async def test_tool_call_text_format(storage, memory):
    """tool_call content is formatted as 'name(key=value, ...)'."""
    tool_call = ToolCall(id="tc_1", name="echo", arguments={"text": "world"})
    llm = ScriptedLLM([[tool_call], "Done."])
    registry = ToolRegistry()
    registry.register(EchoTool())
    channel = CollectingChannel()
    loop = AgentLoop(llm=llm, memory=memory, registry=registry, system_prompt="sys")

    await loop.run(SESSION, "run echo", channel)

    history = await storage.load_history(SESSION.id)
    tool_call_msg = next(m for m in history if m.role == "tool_call")
    assert tool_call_msg.content == "echo(text='world')"


async def test_tool_result_content_truncated_at_2000_chars(storage, memory):
    """Tool results longer than 2000 characters are truncated with [truncated] marker."""

    class LongOutputTool:
        name = "long_output"
        description = "Returns a very long string"
        parameters = {"type": "object", "properties": {}}

        async def execute(self, **_) -> ToolResult:
            return ToolResult(tool_call_id="", content="x" * 3000)

    tool_call = ToolCall(id="tc_1", name="long_output", arguments={})
    llm = ScriptedLLM([[tool_call], "Done."])
    registry = ToolRegistry()
    registry.register(LongOutputTool())
    channel = CollectingChannel()
    loop = AgentLoop(llm=llm, memory=memory, registry=registry, system_prompt="sys")

    await loop.run(SESSION, "get long output", channel)

    history = await storage.load_history(SESSION.id)
    tool_result_msg = next(m for m in history if m.role == "tool_result")
    assert len(tool_result_msg.content) == 2000 + len("\n[truncated]")
    assert tool_result_msg.content.endswith("\n[truncated]")


async def test_tool_events_not_sent_to_channel(storage, memory):
    """tool_call/tool_result messages do not appear as channel output."""
    tool_call = ToolCall(id="tc_1", name="echo", arguments={"text": "hi"})
    llm = ScriptedLLM([[tool_call], "Done."])
    registry = ToolRegistry()
    registry.register(EchoTool())
    channel = CollectingChannel()
    loop = AgentLoop(llm=llm, memory=memory, registry=registry, system_prompt="sys")

    await loop.run(SESSION, "echo hi", channel)

    # Only the final text reply is sent to the channel
    assert channel.sent == ["Done."]


async def test_tool_events_written_for_extra_tools_path(storage, memory):
    """Tool events are persisted when the tool is supplied via extra_tools, not the registry."""
    tool_call = ToolCall(id="tc_1", name="echo", arguments={"text": "via extra"})
    llm = ScriptedLLM([[tool_call], "Done."])
    channel = CollectingChannel()
    loop = AgentLoop(
        llm=llm,
        memory=memory,
        registry=ToolRegistry(),  # empty registry — echo is only in extra_tools
        system_prompt="sys",
    )

    await loop.run(SESSION, "echo via extra", channel, extra_tools=[EchoTool()])

    history = await storage.load_history(SESSION.id)
    roles = [m.role for m in history]
    assert "tool_call" in roles
    assert "tool_result" in roles
    tool_call_msg = next(m for m in history if m.role == "tool_call")
    assert tool_call_msg.content == "echo(text='via extra')"
