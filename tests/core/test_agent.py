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
    InboundMessage,
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
    def __init__(self) -> None:
        self._history: list[Message] = []
        self._global_memory: str = ""

    async def load_history(self, last_n: int | None = None) -> list[Message]:
        if last_n is None:
            return list(self._history)
        return list(self._history[-last_n:])

    async def append_message(self, message: Message) -> None:
        self._history.append(message)

    async def load_global_memory(self) -> str:
        return self._global_memory

    async def save_global_memory(self, content: str) -> None:
        self._global_memory = content

    async def load_cron_jobs(self) -> list:
        return []

    async def save_cron_jobs(self, jobs: list) -> None:
        pass


class CollectingChannel:
    """Channel test double that collects sent messages. streaming=False."""

    streaming = False

    def __init__(self):
        self.sent: list[OutboundMessage] = []

    def receive(self) -> AsyncIterator[InboundMessage]:
        async def _empty() -> AsyncIterator[InboundMessage]:
            empty: tuple[InboundMessage, ...] = ()
            for message in empty:
                yield message

        return _empty()

    async def send(self, message: OutboundMessage) -> None:
        self.sent.append(message)

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


class BuildMessagesFailingMemory(MemoryManager):
    async def build_messages(self, user_message: str, system_prompt: str) -> list[Message]:
        raise RuntimeError("build failed")


class PersistExchangeFailingMemory(MemoryManager):
    async def persist_exchange(
        self,
        channel: str,
        sender_id: str,
        user_message: str,
        assistant_reply: str,
    ) -> None:
        raise RuntimeError("persist failed")


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
    assert [message.text for message in channel.sent] == ["Hello from the bot!"]


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
    assert any("Result received!" in message.text for message in channel.sent)


async def test_history_persisted_after_run(storage, memory):
    llm = ScriptedLLM(["I remember you."])
    channel = CollectingChannel()
    loop = AgentLoop(
        llm=llm, memory=memory, registry=ToolRegistry(), system_prompt="You are a bot."
    )
    await loop.run(SESSION, "Remember me!", channel)
    history = await storage.load_history()
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
    assert [message.text for message in channel.sent] == ["from override"]
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
    assert any("done" in message.text for message in channel.sent)


async def test_outbound_metadata_propagated_to_channel(storage, memory):
    llm = ScriptedLLM(["metadata response"])
    channel = CollectingChannel()
    loop = AgentLoop(
        llm=llm,
        memory=memory,
        registry=ToolRegistry(),
        system_prompt="You are a bot.",
    )

    await loop.run(
        SESSION,
        "Hello!",
        channel,
        outbound_metadata={"k": "v"},
    )

    assert channel.sent[0].metadata.get("k") == "v"


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


async def test_run_degrades_when_build_messages_fails(storage) -> None:
    llm = ScriptedLLM(["fallback response"])
    channel = CollectingChannel()
    loop = AgentLoop(
        llm=llm,
        memory=BuildMessagesFailingMemory(storage=storage),
        registry=ToolRegistry(),
        system_prompt="You are a bot.",
    )

    await loop.run(SESSION, "Hello!", channel)

    assert [message.text for message in channel.sent] == ["fallback response"]


async def test_run_degrades_when_persist_exchange_fails(storage) -> None:
    llm = ScriptedLLM(["still replies"])
    channel = CollectingChannel()
    loop = AgentLoop(
        llm=llm,
        memory=PersistExchangeFailingMemory(storage=storage),
        registry=ToolRegistry(),
        system_prompt="You are a bot.",
    )

    await loop.run(SESSION, "Hello!", channel)

    assert [message.text for message in channel.sent] == ["still replies"]
