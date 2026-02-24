"""
Tests for the manual-only core memory manager behavior.

These tests define the target behavior for the simplified memory model:
system prompt memory injection, bounded labelled history context, and
exchange persistence with channel/sender metadata.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from squidbot.config.schema import OwnerAliasEntry
from squidbot.core.memory import MemoryManager
from squidbot.core.models import Message

if TYPE_CHECKING:
    from squidbot.core.models import CronJob


class InMemoryStorage:
    """In-memory test double for memory persistence."""

    def __init__(self) -> None:
        self._history: list[Message] = []
        self._global_memory: str = ""
        self._cron_jobs: list[CronJob] = []

    async def load_history(self, last_n: int | None = None) -> list[Message]:
        """Return all history or only the last last_n entries."""
        if last_n is None:
            return list(self._history)
        return list(self._history[-last_n:])

    async def append_message(self, message: Message) -> None:
        """Append one message to history."""
        self._history.append(message)

    async def load_global_memory(self) -> str:
        """Load the durable global memory document."""
        return self._global_memory

    async def save_global_memory(self, content: str) -> None:
        """Persist the durable global memory document."""
        self._global_memory = content

    async def load_cron_jobs(self) -> list[CronJob]:
        """Load persisted cron jobs."""
        return list(self._cron_jobs)

    async def save_cron_jobs(self, jobs: list[CronJob]) -> None:
        """Persist cron jobs."""
        self._cron_jobs = list(jobs)


@pytest.fixture
def storage() -> InMemoryStorage:
    """Create a fresh in-memory storage double."""
    return InMemoryStorage()


async def test_build_messages_includes_your_memory_heading_when_present(
    storage: InMemoryStorage,
) -> None:
    """System prompt includes a Your Memory block when global memory is non-empty."""
    await storage.save_global_memory("User prefers concise replies.")
    manager = MemoryManager(storage=storage)

    messages = await manager.build_messages(
        channel="cli",
        sender_id="local",
        user_message="Hello",
        system_prompt="You are a helpful assistant.",
    )

    assert messages[0].role == "system"
    assert "## Your Memory" in messages[0].content
    assert "User prefers concise replies." in messages[0].content


async def test_build_messages_includes_only_last_history_context_messages_labelled(
    storage: InMemoryStorage,
) -> None:
    """Only the last configured history context messages are included and labelled."""
    storage._history = [
        Message(role="user", content="old-1", channel="cli", sender_id="alice"),
        Message(role="assistant", content="old-2", channel="cli", sender_id="assistant"),
        Message(role="user", content="keep-1", channel="cli", sender_id="alice"),
        Message(role="assistant", content="keep-2", channel="cli", sender_id="assistant"),
        Message(role="user", content="keep-3", channel="cli", sender_id="alice"),
    ]
    memory_kwargs: dict[str, Any] = {"history_context_messages": 3}
    manager = MemoryManager(storage=storage, **memory_kwargs)

    messages = await manager.build_messages(
        channel="cli",
        sender_id="alice",
        user_message="follow up",
        system_prompt="sys",
    )

    assert len(messages) == 5  # system + 3 history + user
    history_messages = messages[1:-1]
    assert history_messages[0].content == "[cli / alice]\nkeep-1"
    assert history_messages[1].content == "[cli / assistant]\nkeep-2"
    assert history_messages[2].content == "[cli / alice]\nkeep-3"


async def test_build_messages_does_not_inject_conversation_summary_block(
    storage: InMemoryStorage,
) -> None:
    """System prompt does not include a conversation summary section."""
    manager = MemoryManager(storage=storage)

    messages = await manager.build_messages(
        channel="cli",
        sender_id="local",
        user_message="Hello",
        system_prompt="You are a helpful assistant.",
    )

    assert "## Conversation Summary" not in messages[0].content


async def test_build_messages_labels_owner_for_unscoped_alias(storage: InMemoryStorage) -> None:
    """Unscoped owner aliases label matching sender as owner in any channel."""
    storage._history = [
        Message(role="user", content="hi", channel="email", sender_id="alex@example.com"),
    ]
    aliases = [OwnerAliasEntry(address="alex@example.com")]
    manager = MemoryManager(storage=storage, owner_aliases=aliases)

    messages = await manager.build_messages(
        channel="email",
        sender_id="alex@example.com",
        user_message="follow up",
        system_prompt="sys",
    )

    assert messages[1].content == "[email / owner]\nhi"


async def test_build_messages_scoped_alias_only_labels_in_matching_channel(
    storage: InMemoryStorage,
) -> None:
    """Scoped owner aliases apply only in their configured channel."""
    storage._history = [
        Message(role="user", content="matrix hi", channel="matrix", sender_id="@alex:matrix.org"),
        Message(role="user", content="cli hi", channel="cli", sender_id="@alex:matrix.org"),
    ]
    aliases = [OwnerAliasEntry(address="@alex:matrix.org", channel="matrix")]
    manager = MemoryManager(storage=storage, owner_aliases=aliases)

    messages = await manager.build_messages(
        channel="cli",
        sender_id="local",
        user_message="follow up",
        system_prompt="sys",
    )

    assert messages[1].content == "[matrix / owner]\nmatrix hi"
    assert messages[2].content == "[cli / @alex:matrix.org]\ncli hi"


async def test_build_messages_legacy_history_without_channel_or_sender_is_unchanged(
    storage: InMemoryStorage,
) -> None:
    """Legacy history entries without channel/sender remain unlabelled and do not crash."""
    storage._history = [
        Message(role="user", content="legacy message"),
    ]
    manager = MemoryManager(storage=storage)

    messages = await manager.build_messages(
        channel="cli",
        sender_id="local",
        user_message="new message",
        system_prompt="sys",
    )

    assert messages[1].content == "legacy message"


async def test_persist_exchange_appends_user_then_assistant_with_metadata(
    storage: InMemoryStorage,
) -> None:
    """Persisted exchange stores exactly user then assistant with channel/sender metadata."""
    manager = MemoryManager(storage=storage)

    await manager.persist_exchange(
        channel="matrix",
        sender_id="@alex:matrix.org",
        user_message="hey",
        assistant_reply="hi",
    )

    assert len(storage._history) == 2
    user_msg = storage._history[0]
    assistant_msg = storage._history[1]

    assert user_msg.role == "user"
    assert user_msg.content == "hey"
    assert user_msg.channel == "matrix"
    assert user_msg.sender_id == "@alex:matrix.org"

    assert assistant_msg.role == "assistant"
    assert assistant_msg.content == "hi"
    assert assistant_msg.channel == "matrix"
    assert assistant_msg.sender_id == "assistant"


def test_init_rejects_zero_history_context_messages(storage: InMemoryStorage) -> None:
    """Constructor raises ValueError when history_context_messages is zero."""
    with pytest.raises(ValueError, match="history_context_messages must be > 0"):
        MemoryManager(storage=storage, history_context_messages=0)


def test_init_rejects_negative_history_context_messages(storage: InMemoryStorage) -> None:
    """Constructor raises ValueError when history_context_messages is negative."""
    with pytest.raises(ValueError, match="history_context_messages must be > 0"):
        MemoryManager(storage=storage, history_context_messages=-5)
