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
        self._docs: dict[str, str] = {}
        self._cursors: dict[str, int] = {}

    async def load_history(self, session_id):
        return list(self._histories.get(session_id, []))

    async def append_message(self, session_id, message):
        self._histories.setdefault(session_id, []).append(message)

    async def load_memory_doc(self, session_id):
        return self._docs.get(session_id, "")

    async def save_memory_doc(self, session_id, content):
        self._docs[session_id] = content

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
