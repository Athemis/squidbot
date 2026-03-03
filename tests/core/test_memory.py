"""
Tests for the manual-only core memory manager behavior.

These tests define the target behavior for the simplified memory model:
system prompt memory injection, bounded labelled history context, and
exchange persistence with channel/sender metadata.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from squidbot.config.schema import OwnerAliasEntry
from squidbot.core.memory import MemoryManager
from squidbot.core.models import Message, Session

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
        user_message="follow up",
        system_prompt="sys",
    )

    assert len(messages) == 5  # system + 3 history + user
    history_messages = messages[1:-1]
    assert history_messages[0].content == "[cli / alice]\nkeep-1"
    assert history_messages[1].content == "keep-2"  # assistant messages are not labelled
    assert history_messages[2].content == "[cli / alice]\nkeep-3"


async def test_build_messages_does_not_inject_conversation_summary_block(
    storage: InMemoryStorage,
) -> None:
    """System prompt does not include a conversation summary section."""
    manager = MemoryManager(storage=storage)

    messages = await manager.build_messages(
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
        user_message="follow up",
        system_prompt="sys",
    )

    assert messages[1].content == "[matrix / owner]\nmatrix hi"
    assert messages[2].content == "[cli / @alex:matrix.org]\ncli hi"


async def test_build_messages_owner_alias_matching_is_case_sensitive(
    storage: InMemoryStorage,
) -> None:
    """Owner alias matching is case-sensitive for sender IDs."""
    storage._history = [
        Message(role="user", content="hi", channel="cli", sender_id="alex"),
    ]
    aliases = [OwnerAliasEntry(address="Alex")]
    manager = MemoryManager(storage=storage, owner_aliases=aliases)

    messages = await manager.build_messages(
        user_message="follow up",
        system_prompt="sys",
    )

    assert messages[1].content == "[cli / alex]\nhi"


async def test_build_messages_sender_id_none_with_channel_labels_unknown(
    storage: InMemoryStorage,
) -> None:
    """A missing sender_id in a channel is labelled unknown and does not crash."""
    storage._history = [
        Message(role="user", content="hi", channel="cli", sender_id=None),
    ]
    aliases = [OwnerAliasEntry(address="cli")]
    manager = MemoryManager(storage=storage, owner_aliases=aliases)

    messages = await manager.build_messages(
        user_message="follow up",
        system_prompt="sys",
    )

    assert messages[1].content == "[cli / unknown]\nhi"


async def test_build_messages_checks_scoped_alias_before_returning_unscoped_match(
    storage: InMemoryStorage,
) -> None:
    """A later scoped match must win over an earlier unscoped match."""

    class SpyAlias:
        def __init__(self, address: str, channel: str | None) -> None:
            self._address = address
            self._channel = channel
            self.channel_accesses = 0

        @property
        def address(self) -> str:
            return self._address

        @property
        def channel(self) -> str | None:
            self.channel_accesses += 1
            return self._channel

    scoped_alias = SpyAlias(address="alex", channel="matrix")
    aliases: list[Any] = [SpyAlias(address="alex", channel=None), scoped_alias]
    storage._history = [Message(role="user", content="hi", channel="matrix", sender_id="alex")]
    manager = MemoryManager(storage=storage, owner_aliases=aliases)

    messages = await manager.build_messages(
        user_message="follow up",
        system_prompt="sys",
    )

    assert messages[1].content == "[matrix / owner]\nhi"
    assert scoped_alias.channel_accesses == 1


async def test_build_messages_legacy_history_without_channel_or_sender_is_unchanged(
    storage: InMemoryStorage,
) -> None:
    """Legacy history entries without channel/sender remain unlabelled and do not crash."""
    storage._history = [
        Message(role="user", content="legacy message"),
    ]
    manager = MemoryManager(storage=storage)

    messages = await manager.build_messages(
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
        session_id="matrix:@alex:matrix.org",
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


async def test_persist_exchange_uses_batch_when_available() -> None:
    """persist_exchange must call append_messages (not append_message) when available."""
    append_message_calls: list[Message] = []
    append_messages_calls: list[list[Message]] = []

    class BatchStorage:
        async def load_history(self, last_n: int | None = None) -> list[Message]:
            return []

        async def load_global_memory(self) -> str:
            return ""

        async def append_message(self, message: Message) -> None:
            append_message_calls.append(message)

        async def append_messages(self, messages: list[Message]) -> None:
            append_messages_calls.append(messages)

        async def save_global_memory(self, content: str) -> None: ...
        async def load_cron_jobs(self) -> list:
            return []  # type: ignore[return-value]

        async def save_cron_jobs(self, jobs: list) -> None: ...

    manager = MemoryManager(storage=BatchStorage())  # type: ignore[arg-type]
    await manager.persist_exchange(
        channel="cli",
        sender_id="user",
        user_message="hello",
        assistant_reply="world",
        session_id="cli:user",
    )

    assert len(append_messages_calls) == 1, "append_messages should be called once"
    assert len(append_message_calls) == 0, (
        "append_message should not be called when append_messages is available"
    )
    batch = append_messages_calls[0]
    assert len(batch) == 2
    assert batch[0].role == "user"
    assert batch[0].content == "hello"
    assert batch[1].role == "assistant"
    assert batch[1].content == "world"


def test_init_rejects_zero_history_context_messages(storage: InMemoryStorage) -> None:
    """Constructor raises ValueError when history_context_messages is zero."""
    with pytest.raises(ValueError, match="history_context_messages must be > 0"):
        MemoryManager(storage=storage, history_context_messages=0)


def test_init_rejects_negative_history_context_messages(storage: InMemoryStorage) -> None:
    """Constructor raises ValueError when history_context_messages is negative."""
    with pytest.raises(ValueError, match="history_context_messages must be > 0"):
        MemoryManager(storage=storage, history_context_messages=-5)


async def test_build_messages_loads_history_and_memory_in_parallel() -> None:
    """load_history and load_global_memory must both start before either completes."""
    history_started = asyncio.Event()
    memory_started = asyncio.Event()

    class TrackingStorage:
        async def load_history(self, last_n: int | None = None) -> list[Message]:
            history_started.set()
            # Suspend here so the other coroutine gets a chance to start
            await asyncio.sleep(0)
            return []

        async def load_global_memory(self) -> str:
            memory_started.set()
            await asyncio.sleep(0)
            return ""

        async def append_message(self, message: Message) -> None: ...
        async def save_global_memory(self, content: str) -> None: ...
        async def load_cron_jobs(self) -> list:
            return []  # type: ignore[return-value]

        async def save_cron_jobs(self, jobs: list) -> None: ...

    manager = MemoryManager(storage=TrackingStorage())  # type: ignore[arg-type]
    await manager.build_messages(user_message="hi", system_prompt="sys")

    # Both events must be set — sequential execution would leave one unset when the
    # other completes and the coroutine never yields back to the second.
    assert history_started.is_set(), "load_history was never called"
    assert memory_started.is_set(), "load_global_memory was never called"


async def test_skills_xml_cached_between_calls() -> None:
    """build_skills_xml is called only once when the skill list is unchanged."""
    import squidbot.core.memory as _memory_module
    from squidbot.core.skills import SkillMetadata

    skill = SkillMetadata(
        name="test_skill",
        description="desc",
        location=Path("/f.md"),
        always=False,
        available=True,
    )

    class FakeSkills:
        def list_skills(self) -> list[SkillMetadata]:
            return [skill]

        def load_skill_body(self, name: str) -> str:
            return "body"

    class MinimalStorage:
        async def load_history(self, last_n: int | None = None) -> list[Message]:
            return []

        async def load_global_memory(self) -> str:
            return ""

        async def append_message(self, m: Message) -> None: ...
        async def save_global_memory(self, c: str) -> None: ...
        async def load_cron_jobs(self) -> list:
            return []  # type: ignore[return-value]

        async def save_cron_jobs(self, j: list) -> None: ...

    manager = MemoryManager(
        storage=MinimalStorage(),  # type: ignore[arg-type]
        skills=FakeSkills(),  # type: ignore[arg-type]
    )

    build_calls: list[int] = []
    original_build = _memory_module.build_skills_xml

    def counting_build(skills: list[SkillMetadata]) -> str:
        build_calls.append(1)
        return "<skills/>"

    _memory_module.build_skills_xml = counting_build  # type: ignore[assignment]
    try:
        messages1 = await manager.build_messages("hi", "sys")
        messages2 = await manager.build_messages("hi again", "sys")
    finally:
        _memory_module.build_skills_xml = original_build  # type: ignore[assignment]

    assert len(build_calls) == 1, f"build_skills_xml called {len(build_calls)} times"
    assert "<skills/>" in messages1[0].content, "Cached result missing from first call"
    assert "<skills/>" in messages2[0].content, "Cached result missing from second call"


async def test_always_available_skill_body_injected_into_system_prompt() -> None:
    """Skills with always=True and available=True must have their body appended to the prompt."""
    from squidbot.core.skills import SkillMetadata

    skill = SkillMetadata(
        name="always_skill",
        description="Always-injected skill",
        location=Path("/always.md"),
        always=True,
        available=True,
    )

    class FakeSkills:
        def list_skills(self) -> list[SkillMetadata]:
            return [skill]

        def load_skill_body(self, name: str) -> str:
            return f"<body>{name}</body>"

    class MinimalStorage:
        async def load_history(self, last_n: int | None = None) -> list[Message]:
            return []

        async def load_global_memory(self) -> str:
            return ""

        async def append_message(self, m: Message) -> None: ...

        async def save_global_memory(self, c: str) -> None: ...

        async def load_cron_jobs(self) -> list:
            return []  # type: ignore[return-value]

        async def save_cron_jobs(self, j: list) -> None: ...

    manager = MemoryManager(
        storage=MinimalStorage(),  # type: ignore[arg-type]
        skills=FakeSkills(),  # type: ignore[arg-type]
    )
    messages = await manager.build_messages("hi", "sys")
    assert messages[0].role == "system"
    assert "<body>always_skill</body>" in messages[0].content


async def test_build_messages_applies_session_reset_boundary(storage: InMemoryStorage) -> None:
    """After /new, matching-session history before reset is excluded."""
    storage._history = [
        Message(
            role="user",
            content="old current session",
            channel="cli",
            sender_id="local",
            session_id="cli:local",
        ),
        Message(
            role="assistant",
            content="old reply current session",
            channel="cli",
            sender_id="assistant",
            session_id="cli:local",
        ),
        Message(
            role="user",
            content="other session",
            channel="cli",
            sender_id="other",
            session_id="cli:other",
        ),
    ]
    manager = MemoryManager(storage=storage)
    session = Session(channel="cli", sender_id="local")
    manager.reset_session_context(session)

    messages = await manager.build_messages(
        user_message="new prompt",
        system_prompt="sys",
        session=session,
    )

    contents = [m.content for m in messages[1:-1]]
    assert "[cli / local]\nold current session" not in contents
    assert "other session" in "\n".join(str(c) for c in contents)


async def test_build_messages_reset_boundary_handles_legacy_entries(
    storage: InMemoryStorage,
) -> None:
    """Legacy messages without session_id are matched with channel fallback rules."""
    manager = MemoryManager(storage=storage)
    session = Session(channel="cli", sender_id="local")
    manager.reset_session_context(session)
    reset_at = manager._session_reset_at[session.id]

    storage._history = [
        Message(
            role="user",
            content="legacy other channel",
            channel="matrix",
            sender_id="local",
            timestamp=reset_at,
        ),
        Message(
            role="assistant",
            content="legacy assistant old",
            channel="cli",
            sender_id="assistant",
            timestamp=reset_at - timedelta(microseconds=1),
        ),
        Message(
            role="assistant",
            content="legacy assistant new",
            channel="cli",
            sender_id="assistant",
            timestamp=reset_at,
        ),
        Message(
            role="user",
            content="legacy matching old",
            channel="cli",
            sender_id="local",
            timestamp=reset_at - timedelta(microseconds=1),
        ),
        Message(
            role="user",
            content="legacy matching new",
            channel="cli",
            sender_id="local",
            timestamp=reset_at,
        ),
    ]

    messages = await manager.build_messages(
        user_message="new prompt",
        system_prompt="sys",
        session=session,
    )

    rendered = "\n".join(str(m.content) for m in messages[1:-1])
    assert "legacy other channel" in rendered
    assert "legacy assistant old" not in rendered
    assert "legacy assistant new" in rendered
    assert "legacy matching old" not in rendered
    assert "legacy matching new" in rendered
