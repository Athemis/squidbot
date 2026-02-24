"""
Tests for the core memory manager.

Uses in-memory storage to test consolidation logic and memory.md injection
without touching the filesystem.
"""

from __future__ import annotations

import pytest

from squidbot.config.schema import OwnerAliasEntry
from squidbot.core.memory import MemoryManager
from squidbot.core.models import Message


class InMemoryStorage:
    """Test double for MemoryPort — stores everything in RAM."""

    def __init__(self) -> None:
        self._history: list[Message] = []
        self._global_memory: str = ""
        self._summary: str = ""
        self._cursor: int = 0
        self._cron: list = []

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

    async def load_global_summary(self) -> str:
        return self._summary

    async def save_global_summary(self, content: str) -> None:
        self._summary = content

    async def load_global_cursor(self) -> int:
        return self._cursor

    async def save_global_cursor(self, cursor: int) -> None:
        self._cursor = cursor

    async def load_cron_jobs(self) -> list:
        return self._cron

    async def save_cron_jobs(self, jobs: list) -> None:
        self._cron = jobs


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def manager(storage: InMemoryStorage) -> MemoryManager:
    return MemoryManager(storage=storage)


# ---------------------------------------------------------------------------
# Basic build_messages / persist_exchange
# ---------------------------------------------------------------------------


async def test_build_messages_empty_history(manager: MemoryManager) -> None:
    messages = await manager.build_messages("cli", "local", "Hello", "You are a bot.")
    # system + user = 2 messages
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[-1].role == "user"
    assert messages[-1].content == "Hello"


async def test_build_messages_includes_global_memory(
    manager: MemoryManager, storage: InMemoryStorage
) -> None:
    await storage.save_global_memory("User is a developer.")
    messages = await manager.build_messages("cli", "local", "Hello", "You are a bot.")
    assert "User is a developer." in messages[0].content


async def test_build_messages_includes_global_summary(
    manager: MemoryManager, storage: InMemoryStorage
) -> None:
    await storage.save_global_summary("Previous conversation recap.")
    messages = await manager.build_messages("cli", "local", "Hello", "You are a bot.")
    assert "Previous conversation recap." in messages[0].content


async def test_build_messages_summary_heading_is_conversation(
    manager: MemoryManager, storage: InMemoryStorage
) -> None:
    await storage.save_global_summary("Some summary.")
    messages = await manager.build_messages("cli", "local", "Hello", "You are a bot.")
    assert "## Conversation Summary" in messages[0].content


async def test_build_messages_includes_history(
    manager: MemoryManager, storage: InMemoryStorage
) -> None:
    storage._history = [
        Message(role="user", content="prev", channel="cli", sender_id="local"),
        Message(role="assistant", content="response", channel="cli", sender_id="assistant"),
    ]
    messages = await manager.build_messages("cli", "local", "follow up", "You are a bot.")
    # system + 2 history + user = 4
    assert len(messages) == 4


async def test_persist_exchange(manager: MemoryManager, storage: InMemoryStorage) -> None:
    await manager.persist_exchange("cli", "local", "Hello", "Hi there!")
    assert len(storage._history) == 2
    assert storage._history[0].role == "user"
    assert storage._history[1].role == "assistant"


# ---------------------------------------------------------------------------
# Owner labelling
# ---------------------------------------------------------------------------


async def test_build_messages_labels_owner_by_alias() -> None:
    aliases = [OwnerAliasEntry(address="alex")]
    storage = InMemoryStorage()
    storage._history = [
        Message(role="user", content="hi", channel="cli", sender_id="alex"),
        Message(role="assistant", content="hello", channel="cli", sender_id="assistant"),
    ]
    manager = MemoryManager(storage=storage, owner_aliases=aliases)
    msgs = await manager.build_messages("cli", "alex", "what's up?", "You are helpful.")
    # messages[0] is system, messages[1] is first history message, messages[2] is second
    assert "[cli / owner]" in msgs[1].content
    assert "[cli / assistant]" in msgs[2].content


async def test_build_messages_labels_scoped_alias() -> None:
    aliases = [OwnerAliasEntry(address="@alex:matrix.org", channel="matrix")]
    storage = InMemoryStorage()
    storage._history = [
        Message(role="user", content="hi", channel="matrix", sender_id="@alex:matrix.org"),
    ]
    manager = MemoryManager(storage=storage, owner_aliases=aliases)
    msgs = await manager.build_messages("matrix", "@alex:matrix.org", "hello", "sys")
    assert "[matrix / owner]" in msgs[1].content


async def test_build_messages_scoped_alias_does_not_match_other_channel() -> None:
    aliases = [OwnerAliasEntry(address="@alex:matrix.org", channel="matrix")]
    storage = InMemoryStorage()
    storage._history = [
        Message(role="user", content="hi", channel="cli", sender_id="@alex:matrix.org"),
    ]
    manager = MemoryManager(storage=storage, owner_aliases=aliases)
    msgs = await manager.build_messages("cli", "local", "hello", "sys")
    # scoped alias for matrix should NOT match cli channel
    assert "[cli / owner]" not in msgs[1].content
    assert "@alex:matrix.org" in msgs[1].content


async def test_persist_exchange_stores_channel_and_sender() -> None:
    storage = InMemoryStorage()
    manager = MemoryManager(storage=storage)
    await manager.persist_exchange("cli", "alex", "hello", "hi there")
    assert storage._history[0].channel == "cli"
    assert storage._history[0].sender_id == "alex"
    assert storage._history[1].channel == "cli"
    assert storage._history[1].sender_id == "assistant"


async def test_build_messages_no_label_when_channel_is_none() -> None:
    storage = InMemoryStorage()
    storage._history = [
        Message(role="user", content="legacy message"),  # no channel/sender_id
    ]
    manager = MemoryManager(storage=storage)
    msgs = await manager.build_messages("cli", "local", "hi", "sys")
    # no label prefix when channel is None
    assert msgs[1].content == "legacy message"


async def test_build_messages_labels_unknown_sender_without_alias() -> None:
    storage = InMemoryStorage()
    storage._history = [
        Message(role="user", content="hey", channel="matrix", sender_id="@stranger:matrix.org"),
    ]
    manager = MemoryManager(storage=storage)
    msgs = await manager.build_messages("matrix", "local", "hi", "sys")
    assert "[matrix / @stranger:matrix.org]" in msgs[1].content


async def test_build_messages_labels_unknown_sender_id_as_unknown_when_none() -> None:
    storage = InMemoryStorage()
    storage._history = [
        Message(role="user", content="hey", channel="cli", sender_id=None),
    ]
    manager = MemoryManager(storage=storage)
    msgs = await manager.build_messages("cli", "local", "hi", "sys")
    assert "[cli / unknown]" in msgs[1].content


# ---------------------------------------------------------------------------
# Consolidation tests (adapted for global API)
# ---------------------------------------------------------------------------


class ScriptedLLM:
    """Minimal LLMPort double that returns a fixed summary string."""

    def __init__(self, summary: str) -> None:
        self._summary = summary

    async def chat(self, messages: list[Message], tools: list, *, stream: bool = True):  # type: ignore[override]
        async def _gen():
            yield self._summary

        return _gen()


async def test_consolidation_not_triggered_below_threshold(storage: InMemoryStorage) -> None:
    llm = ScriptedLLM("Summary: talked about nothing.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=10,
        keep_recent_ratio=0.3,
        llm=llm,
    )
    for i in range(5):
        storage._history.append(Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages("cli", "local", "new", "sys")
    assert len(messages) == 7
    doc = await storage.load_global_summary()
    assert doc == ""


async def test_consolidation_triggered_above_threshold(storage: InMemoryStorage) -> None:
    llm = ScriptedLLM("Summary: talked about Python.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=5,
        keep_recent_ratio=0.4,
        llm=llm,
    )
    for i in range(6):
        storage._history.append(Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages("cli", "local", "new", "sys")
    # Only keep_recent=2 history messages + system + new user = 4 total
    assert len(messages) == 4
    doc = await storage.load_global_summary()
    assert "Summary: talked about Python." in doc


async def test_consolidation_appends_to_existing_summary(storage: InMemoryStorage) -> None:
    await storage.save_global_summary("# Existing\nUser likes cats.")
    llm = ScriptedLLM("Summary: discussed dogs.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=3,
        keep_recent_ratio=0.34,  # int(3 * 0.34) = 1 — keeps exactly 1 message verbatim
        llm=llm,
    )
    for i in range(4):
        storage._history.append(Message(role="user", content=f"msg {i}"))
    await manager.build_messages("cli", "local", "new", "sys")
    doc = await storage.load_global_summary()
    assert "User likes cats." in doc
    assert "Summary: discussed dogs." in doc


async def test_consolidation_summary_appears_in_system_prompt(storage: InMemoryStorage) -> None:
    """The consolidated summary must be visible in the system prompt, not just in storage."""
    llm = ScriptedLLM("Summary: key facts here.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=3,
        keep_recent_ratio=0.34,  # int(3 * 0.34) = 1 — keeps exactly 1 message verbatim
        llm=llm,
    )
    for i in range(4):
        storage._history.append(Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages("cli", "local", "new", "sys")
    system_content = messages[0].content
    assert "Summary: key facts here." in system_content


async def test_consolidation_skipped_when_no_llm(storage: InMemoryStorage) -> None:
    # threshold=3, keep_recent=1, load_n=4. 6 msgs total → load last 4.
    # 4 - 0 = 4 > threshold=3, but LLM is None → no consolidation.
    # Result: 4 history + sys + user = 6 messages.
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=3,
        keep_recent_ratio=0.34,  # int(3 * 0.34) = 1 — keeps exactly 1 message verbatim
        llm=None,
    )
    for i in range(6):
        storage._history.append(Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages("cli", "local", "new", "sys")
    assert len(messages) == 6  # 4 loaded + system + user
    doc = await storage.load_global_summary()
    assert doc == ""


async def test_consolidation_warning_fires_one_turn_before_threshold(
    storage: InMemoryStorage,
) -> None:
    """Warning appears in system prompt when history reaches consolidation_threshold - 2."""
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=10,
        keep_recent_ratio=0.3,
        llm=None,
    )
    # Add exactly threshold - 2 = 8 messages
    for i in range(8):
        storage._history.append(Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages("cli", "local", "new", "sys")
    assert "will soon be summarized" in messages[0].content


async def test_consolidation_warning_does_not_fire_below_threshold(
    storage: InMemoryStorage,
) -> None:
    """Warning does not appear when history is below consolidation_threshold - 2."""
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=10,
        keep_recent_ratio=0.3,
        llm=None,
    )
    # Add threshold - 3 = 7 messages (one below warning trigger)
    for i in range(7):
        storage._history.append(Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages("cli", "local", "new", "sys")
    assert "will soon be summarized" not in messages[0].content


async def test_keep_recent_clamped_to_minimum_one(storage: InMemoryStorage) -> None:
    """When threshold * ratio < 1, keep_recent is clamped to 1 instead of 0."""
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=3,
        keep_recent_ratio=0.2,  # int(3 * 0.2) = 0 → clamped to 1
        llm=ScriptedLLM("Summary."),
    )
    for i in range(4):
        storage._history.append(Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages("cli", "local", "new", "sys")
    # 1 recent message kept + system + new user = 3 total
    assert len(messages) == 3


async def test_cursor_default_is_zero(storage: InMemoryStorage) -> None:
    cursor = await storage.load_global_cursor()
    assert cursor == 0


async def test_cursor_roundtrip(storage: InMemoryStorage) -> None:
    await storage.save_global_cursor(42)
    assert await storage.load_global_cursor() == 42


async def test_consolidation_uses_cursor_not_full_history(storage: InMemoryStorage) -> None:
    # With cursor=4, only 2 unconsolidated messages (in loaded window); threshold=4 not exceeded.
    llm = ScriptedLLM("Summary: only new messages.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=4,
        keep_recent_ratio=0.25,  # keep_recent = max(1, int(4*0.25)) = 1
        llm=llm,
    )
    for i in range(6):
        storage._history.append(Message(role="user", content=f"msg {i}"))
    await storage.save_global_cursor(4)

    # load_n = 4 + 1 = 5, so last 5 of 6 msgs loaded.
    # len(history)=5, cursor=4 → 5 - 4 = 1 ≤ threshold=4, no consolidation triggered.
    # Result: 5 history msgs + system + user = 7 messages.
    messages = await manager.build_messages("cli", "local", "new", "sys")
    assert len(messages) == 7  # 5 loaded + system + user
    doc = await storage.load_global_summary()
    assert doc == ""


async def test_consolidation_cursor_advances_after_consolidation(
    storage: InMemoryStorage,
) -> None:
    """Cursor is saved after successful consolidation."""
    llm = ScriptedLLM("Summary: advanced.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=4,
        keep_recent_ratio=0.25,  # keep_recent = max(1, int(4*0.25)) = 1
        llm=llm,
    )
    for i in range(5):
        storage._history.append(Message(role="user", content=f"msg {i}"))
    # cursor=0, len=5, 5-0=5 > 4: consolidation fires
    await manager.build_messages("cli", "local", "new", "sys")
    # cursor should now be 5 - 1 = 4
    cursor = await storage.load_global_cursor()
    assert cursor == 4


async def test_no_consolidation_above_threshold_if_cursor_covers_it(
    storage: InMemoryStorage,
) -> None:
    """If cursor already covers most history, no LLM call is made."""
    call_count = 0

    class CountingLLM:
        async def chat(self, messages: list[Message], tools: list, *, stream: bool = True):  # type: ignore[override]
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
        storage._history.append(Message(role="user", content=f"msg {i}"))
    # Cursor at 9 (only 1 unconsolidated message, below threshold of 4)
    await storage.save_global_cursor(9)
    await manager.build_messages("cli", "local", "new", "sys")
    assert call_count == 0


async def test_consolidation_triggers_multiple_times_over_long_run(
    storage: InMemoryStorage,
) -> None:
    """Consolidation should continue to trigger as new turns accumulate."""
    call_count = 0

    class CountingLLM:
        async def chat(self, messages: list[Message], tools: list, *, stream: bool = True):  # type: ignore[override]
            nonlocal call_count
            call_count += 1

            async def _gen():
                yield f"summary-{call_count}"

            return _gen()

    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=4,
        keep_recent_ratio=0.25,
        llm=CountingLLM(),
    )

    for i in range(15):
        await manager.build_messages("cli", "local", f"user {i}", "sys")
        await manager.persist_exchange("cli", "local", f"user {i}", f"assistant {i}")

    assert call_count >= 2


async def test_global_memory_default_empty(storage: InMemoryStorage) -> None:
    doc = await storage.load_global_memory()
    assert doc == ""


async def test_global_memory_roundtrip(storage: InMemoryStorage) -> None:
    await storage.save_global_memory("User likes Python.")
    assert await storage.load_global_memory() == "User likes Python."


async def test_global_summary_default_empty(storage: InMemoryStorage) -> None:
    doc = await storage.load_global_summary()
    assert doc == ""


async def test_global_summary_roundtrip(storage: InMemoryStorage) -> None:
    await storage.save_global_summary("Summary: discussed Rust.")
    assert await storage.load_global_summary() == "Summary: discussed Rust."


# ---------------------------------------------------------------------------
# C1: Dynamic summary budget
# ---------------------------------------------------------------------------


async def test_consolidation_prompt_scales_with_history_size() -> None:
    """Larger to_summarize windows get a larger sentence budget in the consolidation prompt.

    With the global API, load_history(last_n=threshold+keep_recent) bounds the loaded window.
    Different thresholds produce different to_summarize sizes and therefore different budgets.

    manager_small: threshold=20, keep_recent=2, load_n=22 → to_summarize=20 → budget=5
    manager_large: threshold=100, keep_recent=10, load_n=110 → to_summarize=100 → budget=10
    """
    captured_prompts: list[str] = []

    class CapturingLLM:
        async def chat(self, messages: list[Message], tools: list, *, stream: bool = True):  # type: ignore[override]
            # messages[-1] is the user message with the prompt
            captured_prompts.append(messages[-1].content)

            async def _gen():
                yield "summary"

            return _gen()

    storage_small = InMemoryStorage()
    manager_small = MemoryManager(
        storage=storage_small,
        consolidation_threshold=20,
        keep_recent_ratio=0.1,  # keep_recent = max(1, int(20*0.1)) = 2
        llm=CapturingLLM(),
    )
    storage_large = InMemoryStorage()
    manager_large = MemoryManager(
        storage=storage_large,
        consolidation_threshold=100,
        keep_recent_ratio=0.1,  # keep_recent = max(1, int(100*0.1)) = 10
        llm=CapturingLLM(),
    )

    # Small: fill beyond threshold so consolidation triggers; load_n=22 → loads 22
    for i in range(25):
        storage_small._history.append(Message(role="user", content=f"msg {i}"))
    # Large: fill beyond threshold; load_n=110 → loads 110
    for i in range(115):
        storage_large._history.append(Message(role="user", content=f"msg {i}"))

    await manager_small.build_messages("cli", "local", "new", "sys")
    await manager_large.build_messages("cli", "local", "new", "sys")

    assert len(captured_prompts) == 2
    # Small: to_summarize = 22 - 2 = 20 msgs → budget = max(5, 20//10) = 5 → "5 sentences"
    assert "5 sentences" in captured_prompts[0]
    # Large: to_summarize = 110 - 10 = 100 msgs → budget = max(5, 100//10) = 10 → "10 sentences"
    assert "10 sentences" in captured_prompts[1]


# ---------------------------------------------------------------------------
# C2: System prompt in consolidation LLM call
# ---------------------------------------------------------------------------


async def test_consolidation_uses_system_prompt() -> None:
    """The consolidation LLM call includes a system message as first message."""
    received_messages: list[Message] = []

    class InspectingLLM:
        async def chat(self, messages: list[Message], tools: list, *, stream: bool = True):  # type: ignore[override]
            received_messages.extend(messages)

            async def _gen():
                yield "summary"

            return _gen()

    storage = InMemoryStorage()
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=3,
        keep_recent_ratio=0.34,
        llm=InspectingLLM(),
    )
    for i in range(4):
        storage._history.append(Message(role="user", content=f"msg {i}"))
    await manager.build_messages("cli", "local", "new", "sys")

    assert len(received_messages) >= 2
    assert received_messages[0].role == "system"
    assert "consolidation" in received_messages[0].content.lower()


# ---------------------------------------------------------------------------
# C3: Catch save_global_summary failure
# ---------------------------------------------------------------------------


async def test_consolidation_save_failure_is_caught() -> None:
    """If save_global_summary raises, the turn continues without crashing."""

    class FailingSaveStorage(InMemoryStorage):
        async def save_global_summary(self, content: str) -> None:
            raise OSError("disk full")

    storage = FailingSaveStorage()
    llm = ScriptedLLM("Summary: some content.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=3,
        keep_recent_ratio=0.34,
        llm=llm,
    )
    for i in range(4):
        storage._history.append(Message(role="user", content=f"msg {i}"))

    # Should not raise
    messages = await manager.build_messages("cli", "local", "new", "sys")
    assert len(messages) >= 2


async def test_consolidation_cursor_not_advanced_if_save_fails() -> None:
    """Cursor stays at 0 if save_global_summary fails."""

    class FailingSaveStorage(InMemoryStorage):
        async def save_global_summary(self, content: str) -> None:
            raise OSError("disk full")

    storage = FailingSaveStorage()
    llm = ScriptedLLM("Summary.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=3,
        keep_recent_ratio=0.34,
        llm=llm,
    )
    for i in range(4):
        storage._history.append(Message(role="user", content=f"msg {i}"))
    await manager.build_messages("cli", "local", "new", "sys")
    cursor = await storage.load_global_cursor()
    assert cursor == 0  # not advanced


# ---------------------------------------------------------------------------
# _call_llm helper
# ---------------------------------------------------------------------------


async def test_call_llm_returns_text_on_success() -> None:
    """_call_llm joins streamed chunks and returns stripped text."""
    storage = InMemoryStorage()
    llm = ScriptedLLM("  hello world  ")
    manager = MemoryManager(storage=storage, llm=llm)
    messages = [Message(role="user", content="ping")]
    result = await manager._call_llm(messages)
    assert result == "hello world"


async def test_call_llm_returns_none_on_exception() -> None:
    """_call_llm returns None and logs a warning when the LLM raises."""

    class FailingLLM:
        async def chat(self, messages: list[Message], tools: list, *, stream: bool = True):  # type: ignore[override]
            raise RuntimeError("network error")

    storage = InMemoryStorage()
    manager = MemoryManager(storage=storage, llm=FailingLLM())
    result = await manager._call_llm([Message(role="user", content="ping")])
    assert result is None


async def test_call_llm_returns_none_on_empty_response() -> None:
    """_call_llm returns None when the LLM yields only whitespace."""
    storage = InMemoryStorage()
    llm = ScriptedLLM("   ")
    manager = MemoryManager(storage=storage, llm=llm)
    result = await manager._call_llm([Message(role="user", content="ping")])
    assert result is None


# ---------------------------------------------------------------------------
# _maybe_meta_consolidate: meta-consolidation of global summary
# ---------------------------------------------------------------------------


async def test_meta_consolidation_not_triggered_below_word_limit() -> None:
    """No extra LLM call when summary is within the word limit."""
    call_count = 0

    class CountingLLM:
        async def chat(self, messages: list[Message], tools: list, *, stream: bool = True):  # type: ignore[override]
            nonlocal call_count
            call_count += 1

            async def _gen():
                yield "summary"

            return _gen()

    storage = InMemoryStorage()
    manager = MemoryManager(storage=storage, llm=CountingLLM())
    short_summary = "This is a short session summary."
    result = await manager._maybe_meta_consolidate(short_summary)
    assert result == short_summary
    assert call_count == 0


async def test_meta_consolidation_triggered_above_word_limit() -> None:
    """LLM is called to compress summary when > 600 words."""
    storage = InMemoryStorage()
    llm = ScriptedLLM("Compressed meta summary.")
    manager = MemoryManager(storage=storage, llm=llm)
    fat_summary = " ".join(["word"] * 650)
    result = await manager._maybe_meta_consolidate(fat_summary)
    assert result == "Compressed meta summary."


async def test_meta_consolidation_failure_keeps_original_summary() -> None:
    """When LLM fails, the original oversized summary is returned unchanged."""

    class FailingLLM:
        async def chat(self, messages: list[Message], tools: list, *, stream: bool = True):  # type: ignore[override]
            raise RuntimeError("timeout")

    storage = InMemoryStorage()
    manager = MemoryManager(storage=storage, llm=FailingLLM())
    fat_summary = " ".join(["word"] * 650)
    result = await manager._maybe_meta_consolidate(fat_summary)
    assert result == fat_summary


async def test_consolidate_triggers_meta_consolidation_when_combined_summary_exceeds_limit() -> (
    None
):
    """End-to-end: _consolidate calls _maybe_meta_consolidate when existing + new > 600 words.

    Existing summary is ~580 words. The new consolidation chunk pushes it over 600.
    The scripted LLM returns "Meta summary." for the meta-consolidation call.
    We verify that the *compressed* output is what gets saved — not the raw concatenation.
    """
    # 598 words of existing summary — adding "New chunk." (2 words) gives 600,
    # but "\n\n" splits as empty string and split() skips it, so combined is 600 words.
    # Use 599 words to ensure existing + "\n\n" + "New chunk." = 601 words > 600 trigger.
    existing_summary = " ".join(["existing"] * 599)

    # Two scripted LLM responses:
    # 1st call: normal consolidation → "New chunk."
    # 2nd call: meta-consolidation (combined > 600 words) → "Meta summary."
    responses = ["New chunk.", "Meta summary."]
    response_index = 0

    class TwoShotLLM:
        async def chat(self, messages: list[Message], tools: list, *, stream: bool = True):  # type: ignore[override]
            nonlocal response_index
            text = responses[response_index]
            response_index += 1

            async def _gen():
                yield text

            return _gen()

    storage = InMemoryStorage()
    await storage.save_global_summary(existing_summary)
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=3,
        keep_recent_ratio=0.34,
        llm=TwoShotLLM(),
    )
    for i in range(4):
        storage._history.append(Message(role="user", content=f"msg {i}"))

    await manager.build_messages("cli", "local", "new", "sys")

    saved = await storage.load_global_summary()
    # The saved summary must be the meta-consolidated output, not the raw concatenation
    assert saved == "Meta summary."
    # Both LLM calls were made
    assert response_index == 2
