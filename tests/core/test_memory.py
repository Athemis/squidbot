"""
Tests for the core memory manager.

Uses in-memory storage to test pruning logic and memory.md injection
without touching the filesystem.
"""

import pytest

from squidbot.core.memory import MemoryManager
from squidbot.core.models import Message


class InMemoryStorage:
    """Test double for MemoryPort — stores everything in RAM."""

    def __init__(self):
        self._histories: dict[str, list[Message]] = {}
        self._docs: dict[str, str] = {}

    async def load_history(self, session_id: str) -> list[Message]:
        return list(self._histories.get(session_id, []))

    async def append_message(self, session_id: str, message: Message) -> None:
        self._histories.setdefault(session_id, []).append(message)

    async def load_memory_doc(self, session_id: str) -> str:
        return self._docs.get(session_id, "")

    async def save_memory_doc(self, session_id: str, content: str) -> None:
        self._docs[session_id] = content

    async def load_cron_jobs(self):
        return []

    async def save_cron_jobs(self, jobs) -> None:
        pass


@pytest.fixture
def storage():
    return InMemoryStorage()


@pytest.fixture
def manager(storage):
    return MemoryManager(storage=storage, max_history_messages=5)


async def test_build_messages_empty_session(manager):
    messages = await manager.build_messages(
        session_id="cli:local",
        system_prompt="You are a bot.",
        user_message="Hello",
    )
    # system + user = 2 messages
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[-1].role == "user"
    assert messages[-1].content == "Hello"


async def test_build_messages_includes_memory_doc(manager, storage):
    await storage.save_memory_doc("cli:local", "User is a developer.")
    messages = await manager.build_messages(
        session_id="cli:local",
        system_prompt="You are a bot.",
        user_message="Hello",
    )
    # system prompt should include memory doc content
    assert "User is a developer." in messages[0].content


async def test_build_messages_includes_history(manager, storage):
    await storage.append_message("cli:local", Message(role="user", content="prev"))
    await storage.append_message("cli:local", Message(role="assistant", content="response"))
    messages = await manager.build_messages(
        session_id="cli:local",
        system_prompt="You are a bot.",
        user_message="follow up",
    )
    # system + prev + response + follow up = 4
    assert len(messages) == 4


async def test_prune_oldest_messages_when_over_limit(manager, storage):
    # Add 6 old messages (over the limit of 5)
    for i in range(6):
        await storage.append_message("cli:local", Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages(
        session_id="cli:local",
        system_prompt="You are a bot.",
        user_message="new",
    )
    # Only 5 history messages kept (not 6), plus system + new user
    history_messages = [m for m in messages if m.role != "system"]
    assert len(history_messages) <= 5 + 1  # 5 history + 1 new user msg


async def test_persist_exchange(manager, storage):
    await manager.persist_exchange(
        session_id="cli:local",
        user_message="Hello",
        assistant_reply="Hi there!",
    )
    history = await storage.load_history("cli:local")
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[1].role == "assistant"
