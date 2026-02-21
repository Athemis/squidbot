"""
Tests that mock adapters correctly satisfy the Port protocols.
This ensures our Protocol definitions are complete and usable.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from squidbot.core.models import (
    Message,
    InboundMessage,
    OutboundMessage,
    ToolDefinition,
    ToolResult,
)
from squidbot.core.ports import LLMPort, ChannelPort, ToolPort, MemoryPort, SkillsPort


class MockLLM:
    """Minimal mock LLM that satisfies LLMPort."""

    async def chat(
        self, messages: list[Message], tools: list[ToolDefinition], *, stream: bool = True
    ) -> AsyncIterator[str]:
        async def _gen():
            yield "Hello, world!"

        return _gen()


class MockChannel:
    """Minimal mock channel that satisfies ChannelPort."""

    streaming = False

    def __init__(self, messages: list[InboundMessage]):
        self._messages = messages

    async def receive(self) -> AsyncIterator[InboundMessage]:
        async def _gen():
            for m in self._messages:
                yield m

        return _gen()

    async def send(self, message: OutboundMessage) -> None:
        pass

    async def send_typing(self, session_id: str) -> None:
        pass


class MockTool:
    """Minimal mock tool that satisfies ToolPort."""

    name = "mock_tool"
    description = "A mock tool for testing"
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(tool_call_id="tc_1", content="mock result")


class MockMemory:
    """Minimal mock memory that satisfies MemoryPort."""

    async def load_history(self, session_id: str) -> list[Message]:
        return []

    async def append_message(self, session_id: str, message: Message) -> None:
        pass

    async def load_memory_doc(self, session_id: str) -> str:
        return ""

    async def save_memory_doc(self, session_id: str, content: str) -> None:
        pass


def test_mock_llm_satisfies_protocol():
    llm: LLMPort = MockLLM()  # type: ignore[assignment]
    assert llm is not None


def test_mock_channel_satisfies_protocol():
    channel: ChannelPort = MockChannel([])  # type: ignore[assignment]
    assert channel is not None


def test_mock_tool_satisfies_protocol():
    tool: ToolPort = MockTool()  # type: ignore[assignment]
    assert tool.name == "mock_tool"


class MockSkills:
    """Minimal mock skills loader that satisfies SkillsPort."""

    def list_skills(self) -> list:
        return []

    def load_skill_body(self, name: str) -> str:
        raise FileNotFoundError(name)


def test_mock_memory_satisfies_protocol():
    memory: MemoryPort = MockMemory()  # type: ignore[assignment]
    assert memory is not None


def test_mock_skills_satisfies_protocol():
    skills: SkillsPort = MockSkills()  # type: ignore[assignment]
    assert skills.list_skills() == []
