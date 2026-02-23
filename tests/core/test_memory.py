"""
Tests for the core memory manager.

Uses in-memory storage to test consolidation logic and memory.md injection
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
        self._cursors: dict[str, int] = {}

    async def load_history(self, session_id: str) -> list[Message]:
        return list(self._histories.get(session_id, []))

    async def append_message(self, session_id: str, message: Message) -> None:
        self._histories.setdefault(session_id, []).append(message)

    async def load_memory_doc(self, session_id: str) -> str:
        return self._docs.get(session_id, "")

    async def save_memory_doc(self, session_id: str, content: str) -> None:
        self._docs[session_id] = content

    async def load_consolidated_cursor(self, session_id: str) -> int:
        return self._cursors.get(session_id, 0)

    async def save_consolidated_cursor(self, session_id: str, cursor: int) -> None:
        self._cursors[session_id] = cursor

    async def load_cron_jobs(self):
        return []

    async def save_cron_jobs(self, jobs) -> None:
        pass


@pytest.fixture
def storage():
    return InMemoryStorage()


@pytest.fixture
def manager(storage):
    return MemoryManager(storage=storage)


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


class ScriptedLLM:
    """Minimal LLMPort double that returns a fixed summary string."""

    def __init__(self, summary: str) -> None:
        self._summary = summary

    async def chat(self, messages, tools, *, stream=True):
        async def _gen():
            yield self._summary

        return _gen()


async def test_consolidation_not_triggered_below_threshold(storage):
    llm = ScriptedLLM("Summary: talked about nothing.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=10,
        keep_recent_ratio=0.3,
        llm=llm,
    )
    for i in range(5):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages("s1", "sys", "new")
    assert len(messages) == 7
    doc = await storage.load_memory_doc("s1")
    assert doc == ""


async def test_consolidation_triggered_above_threshold(storage):
    llm = ScriptedLLM("Summary: talked about Python.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=5,
        keep_recent_ratio=0.4,
        llm=llm,
    )
    for i in range(6):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages("s1", "sys", "new")
    # Only keep_recent=2 history messages + system + new user = 4 total
    assert len(messages) == 4
    # Summary was appended to memory.md
    doc = await storage.load_memory_doc("s1")
    assert "Summary: talked about Python." in doc


async def test_consolidation_appends_to_existing_memory_doc(storage):
    await storage.save_memory_doc("s1", "# Existing\nUser likes cats.")
    llm = ScriptedLLM("Summary: discussed dogs.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=3,
        keep_recent_ratio=0.34,  # int(3 * 0.34) = 1 — keeps exactly 1 message verbatim
        llm=llm,
    )
    for i in range(4):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    await manager.build_messages("s1", "sys", "new")
    doc = await storage.load_memory_doc("s1")
    assert "User likes cats." in doc
    assert "Summary: discussed dogs." in doc


async def test_consolidation_summary_appears_in_system_prompt(storage):
    """The consolidated summary must be visible in the system prompt, not just in storage."""
    llm = ScriptedLLM("Summary: key facts here.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=3,
        keep_recent_ratio=0.34,  # int(3 * 0.34) = 1 — keeps exactly 1 message verbatim
        llm=llm,
    )
    for i in range(4):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages("s1", "sys", "new")
    system_content = messages[0].content
    assert "Summary: key facts here." in system_content


async def test_consolidation_skipped_when_no_llm(storage):
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=3,
        keep_recent_ratio=0.34,  # int(3 * 0.34) = 1 — keeps exactly 1 message verbatim
        llm=None,
    )
    for i in range(6):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages("s1", "sys", "new")
    assert len(messages) == 8
    doc = await storage.load_memory_doc("s1")
    assert doc == ""


async def test_consolidation_warning_fires_one_turn_before_threshold(storage):
    """Warning appears in system prompt when history reaches consolidation_threshold - 2."""
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=10,
        keep_recent_ratio=0.3,
        llm=None,
    )
    # Add exactly threshold - 2 = 8 messages
    for i in range(8):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages("s1", "sys", "new")
    assert "will soon be summarized" in messages[0].content


async def test_consolidation_warning_does_not_fire_below_threshold(storage):
    """Warning does not appear when history is below consolidation_threshold - 2."""
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=10,
        keep_recent_ratio=0.3,
        llm=None,
    )
    # Add threshold - 3 = 7 messages (one below warning trigger)
    for i in range(7):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages("s1", "sys", "new")
    assert "will soon be summarized" not in messages[0].content


async def test_keep_recent_clamped_to_minimum_one(storage):
    """When threshold * ratio < 1, keep_recent is clamped to 1 instead of 0."""
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=3,
        keep_recent_ratio=0.2,  # int(3 * 0.2) = 0 → clamped to 1
        llm=ScriptedLLM("Summary."),
    )
    for i in range(4):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages("s1", "sys", "new")
    # 1 recent message kept + system + new user = 3 total
    assert len(messages) == 3


async def test_cursor_default_is_zero(storage):
    cursor = await storage.load_consolidated_cursor("s1")
    assert cursor == 0


async def test_cursor_roundtrip(storage):
    await storage.save_consolidated_cursor("s1", 42)
    assert await storage.load_consolidated_cursor("s1") == 42


async def test_consolidation_uses_cursor_not_full_history(storage):
    """With cursor=4, only 2 unconsolidated messages; threshold=4 not exceeded."""
    llm = ScriptedLLM("Summary: only new messages.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=4,
        keep_recent_ratio=0.25,  # keep_recent = max(1, int(4*0.25)) = 1
        llm=llm,
    )
    for i in range(6):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    await storage.save_consolidated_cursor("s1", 4)

    # Only 6 - 4 = 2 unconsolidated; threshold=4, so no consolidation triggered
    messages = await manager.build_messages("s1", "sys", "new")
    # All 6 history + system + user = 8 (no consolidation)
    assert len(messages) == 8
    doc = await storage.load_memory_doc("s1")
    assert doc == ""


async def test_consolidation_cursor_advances_after_consolidation(storage):
    """Cursor is saved after successful consolidation."""
    llm = ScriptedLLM("Summary: advanced.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=4,
        keep_recent_ratio=0.25,  # keep_recent = max(1, int(4*0.25)) = 1
        llm=llm,
    )
    for i in range(5):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    # cursor=0, len=5, 5-0=5 > 4: consolidation fires
    await manager.build_messages("s1", "sys", "new")
    # cursor should now be 5 - 1 = 4
    cursor = await storage.load_consolidated_cursor("s1")
    assert cursor == 4


async def test_no_consolidation_above_threshold_if_cursor_covers_it(storage):
    """If cursor already covers most history, no LLM call is made."""
    call_count = 0

    class CountingLLM:
        async def chat(self, messages, tools, *, stream=True):
            nonlocal call_count
            call_count += 1

            async def _gen():
                yield "summary"

            return _gen()

    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=4,
        keep_recent_ratio=0.25,
        llm=CountingLLM(),
    )
    for i in range(10):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    # Cursor at 9 (only 1 unconsolidated message, below threshold of 4)
    await storage.save_consolidated_cursor("s1", 9)
    await manager.build_messages("s1", "sys", "new")
    assert call_count == 0
