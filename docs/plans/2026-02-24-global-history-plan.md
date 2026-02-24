# Global Cross-Channel History Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace per-session JSONL history with a single global `history.jsonl` covering all channels, with channel/sender metadata per message and owner alias resolution in config.

**Architecture:** All messages from all channels are appended to one `~/.squidbot/history.jsonl`. Each entry stores the existing fields plus `channel` and `sender_id`. `MemoryManager` loads the last N entries globally (sorted by time), labels owner messages as `[channel / owner]` and others as `[channel / sender_id]`, and injects them into the system prompt. Consolidation runs globally against one `memory/summary.md`. `Session` retains its routing role but no longer scopes history.

**Tech Stack:** Python 3.14, pydantic v2, asyncio, fcntl (stdlib), pytest, ruff, mypy.

**Design doc:** `docs/plans/2026-02-24-global-history-design.md`

---

## Task 1: Extend `Message` model with `channel` and `sender_id`

**Files:**
- Modify: `squidbot/core/models.py`
- Test: `tests/core/test_models.py`

**Step 1: Write the failing test**

In `tests/core/test_models.py`, add:

```python
def test_message_has_channel_and_sender_id() -> None:
    msg = Message(role="user", content="hello", channel="matrix", sender_id="@alice:matrix.org")
    assert msg.channel == "matrix"
    assert msg.sender_id == "@alice:matrix.org"


def test_message_channel_defaults_to_none() -> None:
    msg = Message(role="user", content="hello")
    assert msg.channel is None
    assert msg.sender_id is None
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/core/test_models.py::test_message_has_channel_and_sender_id -v
```

Expected: FAIL — `Message.__init__() got unexpected keyword argument 'channel'`

**Step 3: Add fields to `Message`**

In `squidbot/core/models.py`, in the `Message` dataclass after `timestamp`:

```python
channel: str | None = None
sender_id: str | None = None
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/core/test_models.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add squidbot/core/models.py tests/core/test_models.py
git commit -m "feat(models): add channel and sender_id fields to Message"
```

---

## Task 2: Add `OwnerConfig` to config schema

**Files:**
- Modify: `squidbot/config/schema.py`
- Test: `tests/config/test_schema.py` (create if missing)

**Step 1: Write the failing tests**

```python
from squidbot.config.schema import OwnerAliasEntry, OwnerConfig, Settings


def test_owner_alias_entry_string_form() -> None:
    # plain string alias — matches all channels
    entry = OwnerAliasEntry(address="alex")
    assert entry.address == "alex"
    assert entry.channel is None


def test_owner_alias_entry_scoped() -> None:
    entry = OwnerAliasEntry(address="alex@example.com", channel="email")
    assert entry.channel == "email"


def test_owner_config_defaults_empty() -> None:
    cfg = OwnerConfig()
    assert cfg.aliases == []


def test_settings_has_owner_field() -> None:
    s = Settings()
    assert isinstance(s.owner, OwnerConfig)


def test_settings_load_owner_aliases() -> None:
    import json, tempfile, pathlib
    data = {"owner": {"aliases": [
        "alex",
        {"address": "@alex:matrix.org", "channel": "matrix"},
    ]}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = pathlib.Path(f.name)
    s = Settings.load(path)
    assert len(s.owner.aliases) == 2
    assert s.owner.aliases[0].address == "alex"
    assert s.owner.aliases[1].channel == "matrix"
    path.unlink()
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/config/test_schema.py -v
```

Expected: FAIL — `OwnerAliasEntry` not found

**Step 3: Implement config classes**

In `squidbot/config/schema.py`, add before `Settings`:

```python
class OwnerAliasEntry(BaseModel):
    """A single owner alias, optionally scoped to a specific channel."""

    address: str
    channel: str | None = None

    @classmethod
    def from_value(cls, value: str | dict[str, str]) -> OwnerAliasEntry:
        """Accept either a plain string or a {address, channel} dict."""
        if isinstance(value, str):
            return cls(address=value)
        return cls.model_validate(value)


class OwnerConfig(BaseModel):
    """Identifies the assistant's owner across channels via aliases."""

    aliases: list[OwnerAliasEntry] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_aliases(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Allow aliases to be plain strings or dicts."""
        if isinstance(data, dict) and "aliases" in data:
            data["aliases"] = [
                OwnerAliasEntry.from_value(v) for v in data["aliases"]
            ]
        return data
```

Add `owner: OwnerConfig = Field(default_factory=OwnerConfig)` to `Settings`.

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/config/test_schema.py -v
```

**Step 5: Run full test suite and linter**

```bash
uv run pytest && uv run ruff check .
```

**Step 6: Commit**

```bash
git add squidbot/config/schema.py tests/config/test_schema.py
git commit -m "feat(config): add OwnerConfig with channel-scoped aliases"
```

---

## Task 3: Rewrite `JsonlMemory` for global history

**Files:**
- Modify: `squidbot/adapters/persistence/jsonl.py`
- Test: `tests/adapters/persistence/test_jsonl.py`

**Background:** Replace the session-scoped `load_history` / `append_message` / `load_session_summary` / `save_session_summary` / `load_consolidated_cursor` / `save_consolidated_cursor` with global equivalents. Keep cron and global memory unchanged. Add `fcntl.flock` write locking on `history.jsonl`.

**New storage layout:**
```
<base_dir>/
├── history.jsonl          # all channels, append-only
├── history.meta.json      # global consolidation cursor
├── memory/
│   └── summary.md         # single global summary
├── workspace/
│   └── MEMORY.md          # unchanged
└── cron/
    └── jobs.json           # unchanged
```

**Step 1: Write failing tests**

```python
import pytest
from pathlib import Path
from squidbot.adapters.persistence.jsonl import JsonlMemory
from squidbot.core.models import Message


@pytest.mark.asyncio
async def test_global_history_empty_on_new_storage(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    history = await storage.load_history()
    assert history == []


@pytest.mark.asyncio
async def test_append_and_load_history(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    msg = Message(role="user", content="hello", channel="cli", sender_id="local")
    await storage.append_message(msg)
    history = await storage.load_history()
    assert len(history) == 1
    assert history[0].channel == "cli"
    assert history[0].sender_id == "local"


@pytest.mark.asyncio
async def test_load_history_returns_last_n(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    for i in range(5):
        await storage.append_message(Message(role="user", content=str(i), channel="cli", sender_id="local"))
    history = await storage.load_history(last_n=3)
    assert len(history) == 3
    assert history[0].content == "2"


@pytest.mark.asyncio
async def test_global_summary_roundtrip(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_global_summary("summary text")
    assert await storage.load_global_summary() == "summary text"


@pytest.mark.asyncio
async def test_global_cursor_roundtrip(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    assert await storage.load_global_cursor() == 0
    await storage.save_global_cursor(42)
    assert await storage.load_global_cursor() == 42


@pytest.mark.asyncio
async def test_message_channel_sender_roundtrip(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    msg = Message(role="assistant", content="hi", channel="matrix", sender_id="@bot:matrix.org")
    await storage.append_message(msg)
    loaded = await storage.load_history()
    assert loaded[0].channel == "matrix"
    assert loaded[0].sender_id == "@bot:matrix.org"
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/adapters/persistence/test_jsonl.py -v
```

**Step 3: Rewrite `JsonlMemory`**

Key changes to `squidbot/adapters/persistence/jsonl.py`:

1. Update `_serialize_message` to include `channel` and `sender_id` if set.
2. Update `deserialize_message` to read `channel` and `sender_id` (default `None`).
3. Add `_history_file(base_dir)` → `base_dir / "history.jsonl"` (creates parent).
4. Add `_history_meta_file(base_dir)` → `base_dir / "history.meta.json"`.
5. Add `_global_summary_file(base_dir)` → `base_dir / "memory" / "summary.md"`.
6. Replace `load_history(session_id)` with `load_history(last_n: int | None = None)` — reads `history.jsonl`, returns all or last N entries.
7. Replace `append_message(session_id, message)` with `append_message(message)` — appends to `history.jsonl` with `fcntl.flock` write lock.
8. Replace `load_session_summary` / `save_session_summary` with `load_global_summary()` / `save_global_summary(content)`.
9. Replace `load_consolidated_cursor(session_id)` / `save_consolidated_cursor(session_id, cursor)` with `load_global_cursor()` / `save_global_cursor(cursor)`.

Write lock pattern for `append_message`:

```python
import fcntl

async def append_message(self, message: Message) -> None:
    path = _history_file(self._base)
    def _write() -> None:
        with path.open("a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(_serialize_message(message) + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    await asyncio.to_thread(_write)
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/adapters/persistence/test_jsonl.py -v
```

**Step 5: Run full suite**

```bash
uv run pytest && uv run ruff check . && uv run mypy squidbot/
```

**Step 6: Commit**

```bash
git add squidbot/adapters/persistence/jsonl.py tests/adapters/persistence/test_jsonl.py
git commit -m "feat(persistence): replace per-session JSONL with global history.jsonl"
```

---

## Task 4: Update `MemoryPort` protocol

**Files:**
- Modify: `squidbot/core/ports.py`
- No new tests — protocol changes are verified by mypy and adapter tests

**Step 1: Update `MemoryPort` in `squidbot/core/ports.py`**

Replace all session-scoped history methods with global equivalents:

```python
class MemoryPort(Protocol):
    """
    Interface for session state persistence.

    Manages:
    - Conversation history: global JSONL log of all messages across all channels
    - Global memory document: cross-session notes (MEMORY.md), written by the agent
    - Global summary: cross-channel auto-generated consolidation summary
    - Cron jobs: scheduled task definitions
    """

    async def load_history(self, last_n: int | None = None) -> list[Message]:
        """Load messages from global history. Returns last_n if specified."""
        ...

    async def append_message(self, message: Message) -> None:
        """Append a single message to the global history."""
        ...

    async def load_global_memory(self) -> str:
        """Load the global cross-session memory document."""
        ...

    async def save_global_memory(self, content: str) -> None:
        """Overwrite the global memory document."""
        ...

    async def load_global_summary(self) -> str:
        """Load the auto-generated global consolidation summary."""
        ...

    async def save_global_summary(self, content: str) -> None:
        """Overwrite the global consolidation summary."""
        ...

    async def load_global_cursor(self) -> int:
        """Return the last consolidated message index (0 if none)."""
        ...

    async def save_global_cursor(self, cursor: int) -> None:
        """Persist the consolidation cursor."""
        ...

    async def load_cron_jobs(self) -> list[CronJob]:
        """Load all scheduled jobs."""
        ...

    async def save_cron_jobs(self, jobs: list[CronJob]) -> None:
        """Persist the full list of scheduled jobs."""
        ...
```

**Step 2: Verify mypy**

```bash
uv run mypy squidbot/
```

Fix any type errors before proceeding.

**Step 3: Commit**

```bash
git add squidbot/core/ports.py
git commit -m "refactor(ports): update MemoryPort to global history API"
```

---

## Task 5: Rewrite `MemoryManager` for global history and owner labelling

**Files:**
- Modify: `squidbot/core/memory.py`
- Test: `tests/core/test_memory.py`

**Background:** `MemoryManager` no longer takes `session_id` in `build_messages` / `persist_exchange`. It receives `channel` and `sender_id` instead (for labelling and persistence). Owner identification uses a list of `OwnerAliasEntry` passed at construction.

**Step 1: Write failing tests**

```python
from squidbot.config.schema import OwnerAliasEntry
from squidbot.core.memory import MemoryManager
from squidbot.core.models import Message

# Minimal in-memory MemoryPort double
class InMemoryStorage:
    def __init__(self) -> None:
        self._history: list[Message] = []
        self._global_memory: str = ""
        self._summary: str = ""
        self._cursor: int = 0
        self._cron: list = []

    async def load_history(self, last_n=None):
        if last_n is None:
            return list(self._history)
        return list(self._history[-last_n:])

    async def append_message(self, message):
        self._history.append(message)

    async def load_global_memory(self): return self._global_memory
    async def save_global_memory(self, content): self._global_memory = content
    async def load_global_summary(self): return self._summary
    async def save_global_summary(self, content): self._summary = content
    async def load_global_cursor(self): return self._cursor
    async def save_global_cursor(self, cursor): self._cursor = cursor
    async def load_cron_jobs(self): return self._cron
    async def save_cron_jobs(self, jobs): self._cron = jobs


def _make_manager(aliases=None):
    storage = InMemoryStorage()
    manager = MemoryManager(storage=storage, owner_aliases=aliases or [])
    return manager, storage


@pytest.mark.asyncio
async def test_build_messages_labels_owner_by_alias() -> None:
    aliases = [OwnerAliasEntry(address="alex")]
    manager, storage = _make_manager(aliases)
    storage._history = [
        Message(role="user", content="hi", channel="cli", sender_id="alex"),
        Message(role="assistant", content="hello", channel="cli", sender_id="squidbot"),
    ]
    msgs = await manager.build_messages("cli", "alex", "what's up?", "You are helpful.")
    # history messages should have labels prepended
    assert "[cli / owner]" in msgs[1].content
    assert "[cli / squidbot]" in msgs[2].content


@pytest.mark.asyncio
async def test_build_messages_labels_scoped_alias() -> None:
    aliases = [OwnerAliasEntry(address="@alex:matrix.org", channel="matrix")]
    manager, storage = _make_manager(aliases)
    storage._history = [
        Message(role="user", content="hi", channel="matrix", sender_id="@alex:matrix.org"),
    ]
    msgs = await manager.build_messages("matrix", "@alex:matrix.org", "hello", "sys")
    assert "[matrix / owner]" in msgs[1].content


@pytest.mark.asyncio
async def test_persist_exchange_stores_channel_and_sender(tmp_path) -> None:
    manager, storage = _make_manager()
    await manager.persist_exchange("cli", "alex", "hello", "hi there")
    assert storage._history[0].channel == "cli"
    assert storage._history[0].sender_id == "alex"
    assert storage._history[1].channel == "cli"
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/core/test_memory.py -v
```

**Step 3: Rewrite `MemoryManager`**

Key changes to `squidbot/core/memory.py`:

1. Constructor gains `owner_aliases: list[OwnerAliasEntry] = field(default_factory=list)`.
2. Add `_is_owner(sender_id: str, channel: str) -> bool` — checks aliases (channel-scoped first, then unscoped).
3. `build_messages(channel, sender_id, user_message, system_prompt)` — remove `session_id`, add `channel` + `sender_id`.
4. History loading: `await self._storage.load_history(last_n=self._consolidation_threshold + self._keep_recent)`.
5. Label each history message: prefix content with `[{msg.channel} / {label}]` where label is `"owner"` if `_is_owner`, else `msg.sender_id`.
6. Consolidation: replace all `session_id` references with global equivalents (`load_global_summary`, `save_global_summary`, `load_global_cursor`, `save_global_cursor`).
7. `persist_exchange(channel, sender_id, user_message, assistant_reply)` — pass `channel` and `sender_id` when constructing `Message`.

**Step 4: Run tests**

```bash
uv run pytest tests/core/test_memory.py -v
```

**Step 5: Run full suite**

```bash
uv run pytest && uv run ruff check . && uv run mypy squidbot/
```

**Step 6: Commit**

```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "feat(memory): global history with channel/owner labelling"
```

---

## Task 6: Update `AgentLoop` call sites

**Files:**
- Modify: `squidbot/core/agent.py`
- Test: `tests/core/test_agent.py`

**Background:** `AgentLoop.run()` currently passes `session.id` to `memory.build_messages()` and `memory.persist_exchange()`. These now take `channel` and `sender_id` instead.

**Step 1: Read `agent.py` to find call sites**

Search for `build_messages` and `persist_exchange` in `squidbot/core/agent.py`. Update:

```python
# Before:
messages = await self._memory.build_messages(session.id, self._system_prompt, user_message)
# After:
messages = await self._memory.build_messages(session.channel, session.sender_id, user_message, self._system_prompt)

# Before:
await self._memory.persist_exchange(session.id, user_message, reply)
# After:
await self._memory.persist_exchange(session.channel, session.sender_id, user_message, reply)
```

**Step 2: Run existing agent tests**

```bash
uv run pytest tests/core/test_agent.py -v
```

Fix any failures. Update test doubles that implement the memory interface.

**Step 3: Run full suite**

```bash
uv run pytest && uv run ruff check . && uv run mypy squidbot/
```

**Step 4: Commit**

```bash
git add squidbot/core/agent.py tests/core/test_agent.py
git commit -m "refactor(agent): pass channel/sender_id to memory instead of session_id"
```

---

## Task 7: Update `SearchHistoryTool`

**Files:**
- Modify: `squidbot/adapters/tools/search_history.py`
- Test: `tests/adapters/tools/test_search_history.py`

**Background:** No more multi-file scan — reads `history.jsonl` directly via `JsonlMemory`. Output format changes to `[channel / sender_id]` labels.

**Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_search_finds_match_in_global_history(tmp_path: Path) -> None:
    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.adapters.tools.search_history import SearchHistoryTool

    storage = JsonlMemory(base_dir=tmp_path)
    await storage.append_message(Message(role="user", content="the release is ready", channel="matrix", sender_id="@alex:matrix.org"))
    await storage.append_message(Message(role="assistant", content="great!", channel="matrix", sender_id="squidbot"))

    tool = SearchHistoryTool(base_dir=tmp_path)
    result = await tool.execute(query="release")
    assert not result.is_error
    assert "matrix" in result.content
    assert "@alex:matrix.org" in result.content
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/adapters/tools/test_search_history.py -v
```

**Step 3: Rewrite `SearchHistoryTool`**

- Replace `_load_all_messages` (multi-file scan) with a call to `JsonlMemory(base_dir).load_history()`.
- Update output format: `## Match {i} — [{channel} / {sender_id}] | {ts}`.
- Constructor: `__init__(self, base_dir: Path)` — unchanged signature, but internals use `JsonlMemory`.

**Step 4: Run tests**

```bash
uv run pytest tests/adapters/tools/test_search_history.py -v
```

**Step 5: Run full suite**

```bash
uv run pytest && uv run ruff check . && uv run mypy squidbot/
```

**Step 6: Commit**

```bash
git add squidbot/adapters/tools/search_history.py tests/adapters/tools/test_search_history.py
git commit -m "refactor(search_history): use global history.jsonl directly"
```

---

## Task 8: Update `MemoryWriteTool`

**Files:**
- Modify: `squidbot/adapters/tools/memory_write.py`
- Test: `tests/adapters/tools/test_memory_write.py`

**Background:** `MemoryWriteTool` calls `storage.save_global_memory()` — API unchanged. Verify it still compiles and tests pass after the `MemoryPort` changes.

**Step 1: Run existing tests**

```bash
uv run pytest tests/adapters/tools/test_memory_write.py -v
```

Fix any failures caused by the `MemoryPort` signature changes in Tasks 3–4.

**Step 2: Commit if changes needed**

```bash
git add squidbot/adapters/tools/memory_write.py tests/adapters/tools/test_memory_write.py
git commit -m "fix(memory_write): adapt to updated MemoryPort API"
```

---

## Task 9: Update `_make_agent_loop` and `onboard` in `cli/main.py`

**Files:**
- Modify: `squidbot/cli/main.py`

**Step 1: Pass `owner_aliases` to `MemoryManager`**

In `_make_agent_loop()`:

```python
memory = MemoryManager(
    storage=storage,
    skills=skills,
    llm=llm,
    owner_aliases=settings.owner.aliases,
    consolidation_threshold=settings.agents.consolidation_threshold,
    keep_recent_ratio=settings.agents.keep_recent_ratio,
)
```

**Step 2: Extend onboarding to ask for owner aliases**

In `_run_onboard()`, after existing onboarding steps, add a prompt:

```
What names, nicknames, or addresses should I use to recognise you?
(Enter one per line, or leave blank to skip. Format: plain name, or "address channel" for channel-scoped aliases.)
```

Collect input, build `OwnerConfig.aliases`, write to `settings.owner`, call `settings.save()`.

**Step 3: Run full suite**

```bash
uv run pytest && uv run ruff check . && uv run mypy squidbot/
```

**Step 4: Commit**

```bash
git add squidbot/cli/main.py
git commit -m "feat(cli): pass owner aliases to MemoryManager; extend onboarding"
```

---

## Task 10: Update `AGENTS.md` and `README.md`

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md` (if it documents memory or config)

**Step 1: Update `AGENTS.md` architecture section**

In the directory tree and storage description, replace per-session JSONL references with the new global layout:

```
~/.squidbot/
├── history.jsonl          # global history — all channels
├── history.meta.json      # consolidation cursor
├── memory/
│   └── summary.md         # global consolidation summary
├── workspace/
│   └── MEMORY.md
└── cron/
    └── jobs.json
```

Update `MemoryPort` description and `JsonlMemory` description accordingly.

**Step 2: Update `README.md`**

If README mentions per-session history, update to describe global history and owner alias config.

**Step 3: Run linter**

```bash
uv run ruff check .
```

**Step 4: Commit**

```bash
git add AGENTS.md README.md
git commit -m "docs: update architecture docs for global history"
```

---

## Task 11: Final verification

**Step 1: Run full test suite**

```bash
uv run pytest -v
```

All tests must pass.

**Step 2: Run linter and type checker**

```bash
uv run ruff check . && uv run mypy squidbot/
```

No errors.

**Step 3: Smoke test CLI**

```bash
squidbot agent -m "hello, what channel are we on?"
```

Verify the message is stored in `~/.squidbot/history.jsonl` with `channel` and `sender_id` fields.

**Step 4: Update GitHub issue**

Close https://github.com/Athemis/squidbot/issues/1 with a comment linking to the commits.
