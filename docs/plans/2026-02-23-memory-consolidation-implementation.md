# Memory Consolidation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automatically summarize old conversation history into `memory.md` when it exceeds a threshold, keeping only the most recent messages fully in context.

**Architecture:** `MemoryManager.build_messages()` gains a consolidation step: when `len(history) > consolidation_threshold`, it calls the LLM to summarize the oldest `len(history) - keep_recent` messages and appends the summary to `memory.md`. Only `history[-keep_recent:]` is then included in the returned message list. The JSONL files are never modified. Consolidation is triggered at `build_messages()` time (lazy, on demand).

**Tech Stack:** Python 3.14, existing `LLMPort`, `MemoryPort`, `MemoryManager` in `squidbot/core/memory.py`, `squidbot/config/schema.py`.

---

## Task 1: Add consolidation config to schema

**Files:**
- Modify: `squidbot/config/schema.py`
- Test: `tests/core/test_config.py`

**Step 1: Write the failing test**

In `tests/core/test_config.py`, add:

```python
def test_consolidation_defaults():
    settings = Settings()
    assert settings.agents.consolidation_threshold == 100
    assert settings.agents.keep_recent == 20
    assert settings.agents.consolidation_pool == ""
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/core/test_config.py::test_consolidation_defaults -v
```
Expected: FAIL — `AgentConfig` has no `consolidation_threshold`

**Step 3: Add fields to `AgentConfig`**

In `squidbot/config/schema.py`, extend `AgentConfig`:

```python
class AgentConfig(BaseModel):
    workspace: str = str(Path.home() / ".squidbot" / "workspace")
    restrict_to_workspace: bool = True
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    consolidation_threshold: int = 100   # trigger consolidation above this many messages
    keep_recent: int = 20                # always include this many recent messages verbatim
    consolidation_pool: str = ""         # empty = use llm.default_pool
```

Also extend the `_validate_llm_references` validator to check `consolidation_pool`:

```python
cons_pool = self.agents.consolidation_pool
if cons_pool and cons_pool not in llm.pools:
    raise ValueError(
        f"agents.consolidation_pool '{cons_pool}' not found in llm.pools"
    )
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/core/test_config.py::test_consolidation_defaults -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add squidbot/config/schema.py tests/core/test_config.py
git commit -m "feat(config): add consolidation_threshold, keep_recent, consolidation_pool to AgentConfig"
```

---

## Task 2: Add `consolidate_history()` to `MemoryManager`

**Files:**
- Modify: `squidbot/core/memory.py`
- Test: `tests/core/test_memory.py`

`MemoryManager` needs access to an `LLMPort` to call the LLM for summarization. We inject it optionally — if `None`, consolidation is disabled (safe default for tests that don't pass an LLM).

**Step 1: Write the failing tests**

Add to `tests/core/test_memory.py`:

```python
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
    manager = MemoryManager(storage=storage, max_history_messages=200,
                            consolidation_threshold=10, keep_recent=3, llm=llm)
    for i in range(5):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages("s1", "sys", "new")
    # No consolidation: all 5 history + system + user
    assert len(messages) == 7
    doc = await storage.load_memory_doc("s1")
    assert doc == ""  # memory.md untouched


async def test_consolidation_triggered_above_threshold(storage):
    llm = ScriptedLLM("Summary: talked about Python.")
    manager = MemoryManager(storage=storage, max_history_messages=200,
                            consolidation_threshold=5, keep_recent=2, llm=llm)
    for i in range(6):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages("s1", "sys", "new")
    # Only keep_recent=2 history messages + system + user
    history_in_context = [m for m in messages if m.role not in ("system", "user")]
    assert len(history_in_context) == 2
    # Summary was appended to memory.md
    doc = await storage.load_memory_doc("s1")
    assert "Summary: talked about Python." in doc


async def test_consolidation_appends_to_existing_memory_doc(storage):
    await storage.save_memory_doc("s1", "# Existing\nUser likes cats.")
    llm = ScriptedLLM("Summary: discussed dogs.")
    manager = MemoryManager(storage=storage, max_history_messages=200,
                            consolidation_threshold=3, keep_recent=1, llm=llm)
    for i in range(4):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    await manager.build_messages("s1", "sys", "new")
    doc = await storage.load_memory_doc("s1")
    assert "User likes cats." in doc
    assert "Summary: discussed dogs." in doc


async def test_consolidation_skipped_when_no_llm(storage):
    manager = MemoryManager(storage=storage, max_history_messages=200,
                            consolidation_threshold=3, keep_recent=1, llm=None)
    for i in range(6):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages("s1", "sys", "new")
    # No consolidation: all 6 + system + user
    assert len(messages) == 8
    doc = await storage.load_memory_doc("s1")
    assert doc == ""
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/core/test_memory.py -k "consolidation" -v
```
Expected: FAIL — `MemoryManager.__init__` has no `llm` or `consolidation_threshold` params

**Step 3: Implement in `squidbot/core/memory.py`**

Replace entire file with:

```python
"""
Core memory manager for squidbot.

Coordinates short-term (in-session history) and long-term (memory.md) memory.
The manager is pure domain logic — it takes a MemoryPort and optionally an
LLMPort as dependencies and contains no I/O beyond those ports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from squidbot.core.models import Message
from squidbot.core.ports import MemoryPort, SkillsPort

if TYPE_CHECKING:
    from squidbot.core.ports import LLMPort

_PRUNE_WARNING = (
    "\n\n[System: Conversation history is long. Important information will be "
    "dropped soon. Use the memory_write tool to preserve anything critical before "
    "it leaves context.]\n"
)

_CONSOLIDATION_PROMPT = (
    "You are summarizing a conversation segment for long-term memory. "
    "Write a concise summary (3-10 bullet points) capturing the key facts, "
    "decisions, and context from the messages below. "
    "Focus on information that would be useful in future conversations. "
    "Do NOT include greetings or filler. Reply with only the summary text."
)


class MemoryManager:
    """
    Manages message history and memory documents for agent sessions.

    Responsibilities:
    - Build the full message list for each LLM call (system + history + user)
    - Inject memory.md content into the system prompt
    - Inject skills XML block and always-skill bodies into the system prompt
    - Consolidate old messages into memory.md when history exceeds the threshold
    - Prune old messages when history exceeds the configured limit (legacy fallback)
    - Persist new exchanges after each agent turn
    """

    def __init__(
        self,
        storage: MemoryPort,
        max_history_messages: int = 200,
        skills: SkillsPort | None = None,
        llm: LLMPort | None = None,
        consolidation_threshold: int = 100,
        keep_recent: int = 20,
    ) -> None:
        """
        Args:
            storage: The persistence adapter implementing MemoryPort.
            max_history_messages: Maximum number of history messages to keep
                                  in context (legacy hard-prune fallback).
            skills: Optional skills loader.
            llm: Optional LLM for consolidation. If None, consolidation is disabled.
            consolidation_threshold: Trigger consolidation when history exceeds this.
            keep_recent: Number of most recent messages to keep verbatim after consolidation.
        """
        self._storage = storage
        self._max_history = max_history_messages
        self._skills = skills
        self._llm = llm
        self._consolidation_threshold = consolidation_threshold
        self._keep_recent = keep_recent
        self._warn_threshold = int(max_history_messages * 0.8)

    async def _consolidate(self, session_id: str, history: list[Message]) -> list[Message]:
        """
        Summarize old messages and append the summary to memory.md.

        Args:
            session_id: The session to consolidate.
            history: Full history list (will not be mutated).

        Returns:
            Trimmed history containing only the keep_recent most recent messages.
        """
        assert self._llm is not None
        to_summarize = history[: -self._keep_recent]
        recent = history[-self._keep_recent :]

        # Build a minimal message list for the summarization call
        text_lines = []
        for m in to_summarize:
            if m.role in ("user", "assistant") and m.content:
                text_lines.append(f"{m.role.upper()}: {m.content}")
        conversation_text = "\n".join(text_lines)

        summary_messages = [
            Message(role="system", content=_CONSOLIDATION_PROMPT),
            Message(role="user", content=conversation_text),
        ]

        summary_chunks: list[str] = []
        response_stream = await self._llm.chat(summary_messages, [])
        async for chunk in response_stream:
            if isinstance(chunk, str):
                summary_chunks.append(chunk)
        summary = "".join(summary_chunks).strip()

        if summary:
            existing = await self._storage.load_memory_doc(session_id)
            separator = "\n\n" if existing.strip() else ""
            await self._storage.save_memory_doc(
                session_id,
                existing + separator + summary,
            )

        return recent

    async def build_messages(
        self,
        session_id: str,
        system_prompt: str,
        user_message: str,
    ) -> list[Message]:
        """
        Construct the full message list for an LLM call.

        Runs consolidation if history exceeds consolidation_threshold and an
        LLM is available. Falls back to hard-prune if consolidation is disabled.

        Layout: [system_prompt + memory.md + skills] + [history (trimmed)] + [user_message]

        Args:
            session_id: Unique session identifier.
            system_prompt: The base system prompt (AGENTS.md content).
            user_message: The current user input.

        Returns:
            Ordered list of messages ready to send to the LLM.
        """
        memory_doc = await self._storage.load_memory_doc(session_id)
        history = await self._storage.load_history(session_id)

        # Consolidation: summarize old messages into memory.md
        if self._llm is not None and len(history) > self._consolidation_threshold:
            history = await self._consolidate(session_id, history)
            # Reload memory_doc — consolidation may have updated it
            memory_doc = await self._storage.load_memory_doc(session_id)

        # Legacy hard-prune fallback (when consolidation is disabled)
        near_limit = len(history) >= self._warn_threshold
        if len(history) > self._max_history:
            history = history[-self._max_history :]

        # Build system prompt
        full_system = system_prompt
        if memory_doc.strip():
            full_system += f"\n\n## Your Memory\n\n{memory_doc}"

        if self._skills is not None:
            from squidbot.core.skills import build_skills_xml  # noqa: PLC0415

            skill_list = self._skills.list_skills()
            full_system += f"\n\n{build_skills_xml(skill_list)}"
            for skill in skill_list:
                if skill.always and skill.available:
                    body = self._skills.load_skill_body(skill.name)
                    full_system += f"\n\n{body}"

        if near_limit and self._llm is None:
            full_system += _PRUNE_WARNING

        messages: list[Message] = [
            Message(role="system", content=full_system),
            *history,
            Message(role="user", content=user_message),
        ]
        return messages

    async def persist_exchange(
        self,
        session_id: str,
        user_message: str,
        assistant_reply: str,
    ) -> None:
        """
        Save a completed user–assistant exchange to history.

        Args:
            session_id: Unique session identifier.
            user_message: The user's input text.
            assistant_reply: The final text response from the assistant.
        """
        await self._storage.append_message(session_id, Message(role="user", content=user_message))
        await self._storage.append_message(
            session_id, Message(role="assistant", content=assistant_reply)
        )
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/core/test_memory.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "feat(core): add memory consolidation — summarize old history into memory.md"
```

---

## Task 3: Wire consolidation into `cli/main.py`

**Files:**
- Modify: `squidbot/cli/main.py`

**Step 1: Find `MemoryManager` construction and pass LLM + consolidation params**

Search for `MemoryManager(` in `squidbot/cli/main.py`. Update the call to include:

```python
llm=llm,
consolidation_threshold=settings.agents.consolidation_threshold,
keep_recent=settings.agents.keep_recent,
```

The LLM instance should be the pooled adapter already constructed earlier in `_make_agent_loop()`.

**Step 2: Run all tests**

```bash
uv run pytest -v
```
Expected: all PASS

**Step 3: Commit**

```bash
git add squidbot/cli/main.py
git commit -m "feat(cli): wire consolidation config into MemoryManager at agent startup"
```

---

## Task 4: Update README config example

**Files:**
- Modify: `README.md`

**Step 1: Add consolidation fields to the agents block in the README config example**

```yaml
agents:
  workspace: "~/.squidbot/workspace"
  restrict_to_workspace: true
  consolidation_threshold: 100   # summarize history into memory.md above this many messages
  keep_recent: 20                # keep this many recent messages verbatim in context
  consolidation_pool: ""         # optional — defaults to llm.default_pool
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document consolidation_threshold and keep_recent in README config example"
```

---

## Verification

```bash
uv run pytest -v
uv run ruff check .
uv run mypy squidbot/
```

All must pass before considering this feature complete.
