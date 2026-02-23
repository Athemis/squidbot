# Remove Pruning / Pre-Consolidation Warning Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove dead pruning code from `MemoryManager`, replace `_PRUNE_WARNING` with a
`_CONSOLIDATION_WARNING` that fires one turn before consolidation, and replace `keep_recent: int`
with `keep_recent_ratio: float` so the verbatim window scales with the consolidation threshold.

**Architecture:** All changes are in `config/schema.py`, `core/memory.py`, `cli/main.py`,
and their tests. No new files. No new ports or adapters. The consolidation logic (`_consolidate()`)
is unchanged.

**Tech Stack:** Python 3.14, pytest, pydantic v2, ruff, mypy

---

### Task 1: Replace `keep_recent` with `keep_recent_ratio` in config

**Files:**
- Modify: `squidbot/config/schema.py:67-88`
- Modify: `tests/core/test_config.py:245-259`

**Step 1: Write the failing tests**

In `tests/core/test_config.py`, replace the three consolidation tests at the bottom of the file:

```python
def test_consolidation_defaults():
    settings = Settings()
    assert settings.agents.consolidation_threshold == 100
    assert settings.agents.keep_recent_ratio == 0.2
    assert not hasattr(settings.agents, "keep_recent")
    assert not hasattr(settings.agents, "consolidation_pool")


def test_keep_recent_ratio_must_be_between_0_and_1_exclusive():
    with pytest.raises(ValidationError):
        AgentConfig(consolidation_threshold=100, keep_recent_ratio=0.0)
    with pytest.raises(ValidationError):
        AgentConfig(consolidation_threshold=100, keep_recent_ratio=1.0)
    with pytest.raises(ValidationError):
        AgentConfig(consolidation_threshold=100, keep_recent_ratio=1.5)


def test_keep_recent_ratio_valid():
    cfg = AgentConfig(consolidation_threshold=100, keep_recent_ratio=0.3)
    assert cfg.keep_recent_ratio == 0.3
```

**Step 2: Run tests to verify they fail**

```
uv run pytest tests/core/test_config.py::test_consolidation_defaults \
              tests/core/test_config.py::test_keep_recent_ratio_must_be_between_0_and_1_exclusive \
              tests/core/test_config.py::test_keep_recent_ratio_valid -v
```

Expected: FAIL (attribute does not exist yet)

**Step 3: Update `AgentConfig` in `squidbot/config/schema.py`**

Replace the `AgentConfig` class:

```python
class AgentConfig(BaseModel):
    """Configuration for agent behavior."""

    workspace: str = str(Path.home() / ".squidbot" / "workspace")
    restrict_to_workspace: bool = True
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    # TODO: replace with token-based threshold derived from the model's context window size
    consolidation_threshold: int = 100
    keep_recent_ratio: float = 0.2

    @model_validator(mode="after")
    def _validate_consolidation(self) -> AgentConfig:
        """Validate consolidation config values are consistent and in range."""
        if self.consolidation_threshold <= 0:
            raise ValueError("agents.consolidation_threshold must be > 0")
        if not (0 < self.keep_recent_ratio < 1):
            raise ValueError("agents.keep_recent_ratio must be between 0 and 1 (exclusive)")
        return self
```

**Step 4: Run tests to verify they pass**

```
uv run pytest tests/core/test_config.py -v
```

Expected: all pass (old `keep_recent` tests will now fail — delete them in this step too)

Delete from `tests/core/test_config.py`:
- `test_keep_recent_must_be_less_than_consolidation_threshold` (line 252)
- `test_keep_recent_must_be_positive` (line 257)

Re-run: all pass.

**Step 5: Commit**

```bash
git add squidbot/config/schema.py tests/core/test_config.py
git commit -m "feat(config): replace keep_recent int with keep_recent_ratio float"
```

---

### Task 2: Update `MemoryManager` — remove pruning, add consolidation warning

**Files:**
- Modify: `squidbot/core/memory.py`
- Modify: `tests/core/test_memory.py`

**Step 1: Write the failing tests**

In `tests/core/test_memory.py`:

1. Delete `test_prune_oldest_messages_when_over_limit` (line 86–97).

2. Replace the `manager` fixture (line 45–47) — remove `max_history_messages=5`:

```python
@pytest.fixture
def manager(storage):
    return MemoryManager(storage=storage)
```

3. Remove `max_history_messages=200` from all consolidation tests (lines 128, 145, 165, 183, 198).
   Also replace `keep_recent=N` with `keep_recent_ratio=` using the equivalent ratio:
   - `keep_recent=3, consolidation_threshold=10` → `keep_recent_ratio=0.3, consolidation_threshold=10`
   - `keep_recent=2, consolidation_threshold=5` → `keep_recent_ratio=0.4, consolidation_threshold=5`
   - `keep_recent=1, consolidation_threshold=3` → `keep_recent_ratio=0.34, consolidation_threshold=3`
     (Note: `int(3 * 0.34) = 1` ✓)

4. Add two new warning tests at the bottom of the file:

```python
async def test_consolidation_warning_fires_one_turn_before_threshold(storage):
    """Warning appears in system prompt when history is consolidation_threshold - 2 or more."""
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
```

**Step 2: Run tests to verify they fail**

```
uv run pytest tests/core/test_memory.py -v
```

Expected: multiple failures (parameter not found, warning tests fail)

**Step 3: Update `squidbot/core/memory.py`**

Replace the entire file content:

```python
"""
Core memory manager for squidbot.

Coordinates short-term (in-session history) and long-term (memory.md) memory.
The manager is pure domain logic — it takes a MemoryPort as dependency
and contains no I/O or external service calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from squidbot.core.models import Message
from squidbot.core.ports import MemoryPort, SkillsPort

if TYPE_CHECKING:
    from squidbot.core.ports import LLMPort

# Injected into the system prompt one turn before consolidation fires.
# Prompts the agent to use memory_write to preserve anything critical.
_CONSOLIDATION_WARNING = (
    "\n\n[System: Conversation history will soon be summarized and condensed. "
    "Use the memory_write tool now to preserve anything critical before it happens.]\n"
)

_CONSOLIDATION_PROMPT = (
    "Summarize the following conversation history into a concise memory entry. "
    "Focus on key facts, decisions, and context useful for future conversations. "
    "Do not include small talk or filler.\n\n"
    "Conversation history:\n{history}\n\n"
    "Provide a brief summary (2-5 sentences) suitable for appending to a memory document."
)


class MemoryManager:
    """
    Manages message history and memory documents for agent sessions.

    Responsibilities:
    - Build the full message list for each LLM call (system + history + user)
    - Inject memory.md content into the system prompt
    - Inject skills XML block and always-skill bodies into the system prompt
    - Warn the agent one turn before consolidation via _CONSOLIDATION_WARNING
    - Consolidate old messages into memory.md when history exceeds the threshold
    - Persist new exchanges after each agent turn
    """

    def __init__(
        self,
        storage: MemoryPort,
        skills: SkillsPort | None = None,
        llm: LLMPort | None = None,
        consolidation_threshold: int = 100,
        keep_recent_ratio: float = 0.2,
    ) -> None:
        """
        Args:
            storage: The persistence adapter implementing MemoryPort.
            skills: Optional skills loader. If provided, injects skill metadata
                    and always-skill bodies into every system prompt.
            llm: Optional LLM adapter for history consolidation. If None,
                 consolidation is disabled.
            consolidation_threshold: Number of messages that triggers consolidation.
            keep_recent_ratio: Fraction of consolidation_threshold to keep verbatim
                               after consolidation (e.g. 0.2 = 20%).
        """
        self._storage = storage
        self._skills = skills
        self._llm = llm
        self._consolidation_threshold = consolidation_threshold
        self._keep_recent = int(consolidation_threshold * keep_recent_ratio)

    async def build_messages(
        self,
        session_id: str,
        system_prompt: str,
        user_message: str,
    ) -> list[Message]:
        """
        Construct the full message list for an LLM call.

        Layout: [system_prompt + memory.md + skills + optional warning] + [history] + [user_message]

        Args:
            session_id: Unique session identifier.
            system_prompt: The base system prompt (AGENTS.md content).
            user_message: The current user input.

        Returns:
            Ordered list of messages ready to send to the LLM.
        """
        memory_doc = await self._storage.load_memory_doc(session_id)
        history = await self._storage.load_history(session_id)

        # Consolidate history if over threshold and LLM available
        if len(history) > self._consolidation_threshold and self._llm is not None:
            history = await self._consolidate(session_id, history)
            # Reload memory_doc so the freshly written summary appears in the system prompt
            memory_doc = await self._storage.load_memory_doc(session_id)

        # Build system prompt with memory document appended
        full_system = system_prompt
        if memory_doc.strip():
            full_system += f"\n\n## Your Memory\n\n{memory_doc}"

        # Inject skills: XML index + full bodies of always-skills
        if self._skills is not None:
            from squidbot.core.skills import build_skills_xml  # noqa: PLC0415

            skill_list = self._skills.list_skills()
            full_system += f"\n\n{build_skills_xml(skill_list)}"
            for skill in skill_list:
                if skill.always and skill.available:
                    body = self._skills.load_skill_body(skill.name)
                    full_system += f"\n\n{body}"

        # Warn the agent one turn before consolidation fires
        if len(history) >= self._consolidation_threshold - 2:
            full_system += _CONSOLIDATION_WARNING

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

        Tool calls/results within the exchange are handled by the agent loop
        and appended separately via append_message.

        Args:
            session_id: Unique session identifier.
            user_message: The user's input text.
            assistant_reply: The final text response from the assistant.
        """
        await self._storage.append_message(session_id, Message(role="user", content=user_message))
        await self._storage.append_message(
            session_id, Message(role="assistant", content=assistant_reply)
        )

    async def _consolidate(self, session_id: str, history: list[Message]) -> list[Message]:
        """
        Summarize old messages and append to memory.md, returning recent messages.

        Takes messages[:-keep_recent] to summarize, keeps [-keep_recent:] verbatim.

        Args:
            session_id: Unique session identifier.
            history: Full message history.

        Returns:
            Only the recent messages to keep in context.
        """
        to_summarize = history[: -self._keep_recent]
        recent = history[-self._keep_recent :]

        # Build text from user/assistant messages only
        history_text = ""
        for msg in to_summarize:
            if msg.role in ("user", "assistant"):
                history_text += f"{msg.role}: {msg.content}\n"

        if not history_text.strip():
            return recent

        # Call LLM for summary (self._llm is non-None; caller guarantees this)
        llm = self._llm
        assert llm is not None  # noqa: S101 — narrowing for type checker
        prompt = _CONSOLIDATION_PROMPT.format(history=history_text)
        summary_messages = [Message(role="user", content=prompt)]
        try:
            summary_chunks: list[str] = []
            response_stream = await llm.chat(summary_messages, [])
            async for chunk in response_stream:
                if isinstance(chunk, str):
                    summary_chunks.append(chunk)
            summary = "".join(summary_chunks).strip()
        except Exception as e:
            from loguru import logger  # noqa: PLC0415

            logger.warning("Consolidation LLM call failed, skipping: {}", e)
            return recent

        if not summary:
            return recent

        # Append to existing memory.md
        existing = await self._storage.load_memory_doc(session_id)
        updated = f"{existing}\n\n{summary}" if existing.strip() else summary
        await self._storage.save_memory_doc(session_id, updated)

        return recent
```

**Step 4: Run tests to verify they pass**

```
uv run pytest tests/core/test_memory.py -v
```

Expected: all pass

**Step 5: Commit**

```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "feat(core): replace pruning with pre-consolidation warning, keep_recent_ratio"
```

---

### Task 3: Update `cli/main.py` wiring

**Files:**
- Modify: `squidbot/cli/main.py:436-443`

**Step 1: Update the `MemoryManager(...)` call**

Replace:

```python
    memory = MemoryManager(
        storage=storage,
        max_history_messages=200,
        skills=skills,
        llm=llm,
        consolidation_threshold=settings.agents.consolidation_threshold,
        keep_recent=settings.agents.keep_recent,
    )
```

With:

```python
    memory = MemoryManager(
        storage=storage,
        skills=skills,
        llm=llm,
        consolidation_threshold=settings.agents.consolidation_threshold,
        keep_recent_ratio=settings.agents.keep_recent_ratio,
    )
```

**Step 2: Run full test suite + lint + type-check**

```
uv run pytest -v
uv run ruff check .
uv run mypy squidbot/
```

Expected: all pass, no errors

**Step 3: Commit**

```bash
git add squidbot/cli/main.py
git commit -m "fix(cli): wire keep_recent_ratio into MemoryManager, drop max_history_messages"
```

---

### Task 4: Update README

**Files:**
- Modify: `README.md`

**Step 1: Find and update the consolidation config table**

Search for `keep_recent` in README.md. Replace the row:

```
| `agents.keep_recent` | `20` | Messages kept verbatim after consolidation |
```

With:

```
| `agents.keep_recent_ratio` | `0.2` | Fraction of `consolidation_threshold` kept verbatim after consolidation (e.g. 0.2 = 20 messages when threshold is 100) |
```

**Step 2: Run tests one final time**

```
uv run pytest -v
uv run ruff check .
```

Expected: all pass

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README for keep_recent_ratio config field"
```
