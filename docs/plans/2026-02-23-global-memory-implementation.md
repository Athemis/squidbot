# Global Memory Redesign (Feature B) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the per-session `memory.md` with a two-level model: a global `MEMORY.md` for cross-session facts (agent-curated via `memory_write`) and a per-session `summary.md` for auto-generated consolidation summaries.

**Architecture:** `MemoryPort` gets two new method pairs (`load/save_global_memory`, `load/save_session_summary`). The old `load/save_memory_doc` pair is removed. `MemoryManager.build_messages()` injects both into the system prompt. `MemoryWriteTool` writes to global memory. `_consolidate()` writes to session summary. Filesystem layout: `workspace/MEMORY.md` and `memory/<session-id>/summary.md`.

**Tech Stack:** Python 3.14, pytest, existing squidbot ports/adapters pattern.

**Prerequisite:** Feature A (consolidation cursor) must be implemented first. This plan assumes `load/save_consolidated_cursor` already exist on `MemoryPort` and `JsonlMemory`.

---

### Task 1: Add new methods to `MemoryPort` and remove old ones

**Files:**
- Modify: `squidbot/core/ports.py`
- Modify: `tests/core/test_memory.py` (InMemoryStorage)
- Modify: `tests/core/test_agent.py` (InMemoryStorage)

**Step 1: Write failing tests for new storage methods**

Add to `tests/core/test_memory.py`:

```python
async def test_global_memory_default_empty(storage):
    doc = await storage.load_global_memory()
    assert doc == ""


async def test_global_memory_roundtrip(storage):
    await storage.save_global_memory("User likes Python.")
    assert await storage.load_global_memory() == "User likes Python."


async def test_session_summary_default_empty(storage):
    doc = await storage.load_session_summary("s1")
    assert doc == ""


async def test_session_summary_roundtrip(storage):
    await storage.save_session_summary("s1", "Summary: discussed Rust.")
    assert await storage.load_session_summary("s1") == "Summary: discussed Rust."


async def test_session_summary_isolated_per_session(storage):
    await storage.save_session_summary("s1", "s1 summary")
    await storage.save_session_summary("s2", "s2 summary")
    assert await storage.load_session_summary("s1") == "s1 summary"
    assert await storage.load_session_summary("s2") == "s2 summary"
```

Run: `uv run pytest tests/core/test_memory.py::test_global_memory_default_empty -v`
Expected: FAIL — `InMemoryStorage` has no `load_global_memory`

**Step 2: Update `InMemoryStorage` in test files**

In `tests/core/test_memory.py`, update `InMemoryStorage`:

- Remove `load_memory_doc` / `save_memory_doc`
- Add `self._global_memory: str = ""` and `self._summaries: dict[str, str] = {}` to `__init__`
- Add:

```python
async def load_global_memory(self) -> str:
    return self._global_memory

async def save_global_memory(self, content: str) -> None:
    self._global_memory = content

async def load_session_summary(self, session_id: str) -> str:
    return self._summaries.get(session_id, "")

async def save_session_summary(self, session_id: str, content: str) -> None:
    self._summaries[session_id] = content
```

Apply the same change to `InMemoryStorage` in `tests/core/test_agent.py`.

Update the existing test `test_build_messages_includes_memory_doc` to use the new API:

```python
async def test_build_messages_includes_global_memory(manager, storage):
    await storage.save_global_memory("User is a developer.")
    messages = await manager.build_messages(
        session_id="cli:local",
        system_prompt="You are a bot.",
        user_message="Hello",
    )
    assert "User is a developer." in messages[0].content
```

**Step 3: Update `MemoryPort` protocol**

In `squidbot/core/ports.py`, replace `load_memory_doc` / `save_memory_doc` with:

```python
async def load_global_memory(self) -> str:
    """Load the global cross-session memory document."""
    ...

async def save_global_memory(self, content: str) -> None:
    """Overwrite the global memory document."""
    ...

async def load_session_summary(self, session_id: str) -> str:
    """Load the auto-generated consolidation summary for this session."""
    ...

async def save_session_summary(self, session_id: str, content: str) -> None:
    """Overwrite the session consolidation summary."""
    ...
```

**Step 4: Run tests**

Run: `uv run pytest tests/core/test_memory.py tests/core/test_agent.py -v`
Expected: Port-related tests PASS; tests that call `build_messages` may fail until Task 2

**Step 5: Commit**

```bash
git add squidbot/core/ports.py tests/core/test_memory.py tests/core/test_agent.py
git commit -m "feat(core): replace load/save_memory_doc with global+session memory in MemoryPort"
```

---

### Task 2: Implement new methods in `JsonlMemory`

**Files:**
- Modify: `squidbot/adapters/persistence/jsonl.py`
- Create: `tests/adapters/persistence/test_jsonl_global_memory.py`

**Step 1: Write failing tests**

Create `tests/adapters/persistence/test_jsonl_global_memory.py`:

```python
"""Tests for JsonlMemory global memory and session summary persistence."""

from __future__ import annotations

import pytest

from squidbot.adapters.persistence.jsonl import JsonlMemory


async def test_global_memory_default_empty(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    assert await storage.load_global_memory() == ""


async def test_global_memory_roundtrip(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_global_memory("User likes Python.")
    assert await storage.load_global_memory() == "User likes Python."


async def test_global_memory_file_location(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_global_memory("facts")
    assert (tmp_path / "workspace" / "MEMORY.md").exists()


async def test_session_summary_default_empty(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    assert await storage.load_session_summary("sess1") == ""


async def test_session_summary_roundtrip(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_session_summary("sess1", "Summary text.")
    assert await storage.load_session_summary("sess1") == "Summary text."


async def test_session_summary_file_location(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_session_summary("sess1", "text")
    assert (tmp_path / "memory" / "sess1" / "summary.md").exists()


async def test_session_summary_safe_id(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_session_summary("matrix:room1", "text")
    assert (tmp_path / "memory" / "matrix__room1" / "summary.md").exists()
```

Run: `uv run pytest tests/adapters/persistence/test_jsonl_global_memory.py -v`
Expected: All FAIL

**Step 2: Update `JsonlMemory`**

In `squidbot/adapters/persistence/jsonl.py`:

Update the module docstring to reflect new layout:

```
<base_dir>/
├── workspace/
│   └── MEMORY.md             # global cross-session memory
├── sessions/
│   ├── <session-id>.jsonl    # conversation history
│   └── <session-id>.meta.json  # consolidation cursor
├── memory/
│   └── <session-id>/
│       └── summary.md        # auto-generated consolidation summary
└── cron/
    └── jobs.json
```

Replace `_memory_file` helper with two helpers:

```python
def _global_memory_file(base_dir: Path) -> Path:
    """Return the global MEMORY.md path."""
    path = base_dir / "workspace" / "MEMORY.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _session_summary_file(base_dir: Path, session_id: str) -> Path:
    """Return the session summary.md path."""
    safe_id = session_id.replace(":", "__")
    path = base_dir / "memory" / safe_id / "summary.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
```

Replace `load_memory_doc` / `save_memory_doc` methods:

```python
async def load_global_memory(self) -> str:
    """Load the global cross-session memory document."""
    path = _global_memory_file(self._base)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")

async def save_global_memory(self, content: str) -> None:
    """Overwrite the global memory document."""
    path = _global_memory_file(self._base)
    path.write_text(content, encoding="utf-8")

async def load_session_summary(self, session_id: str) -> str:
    """Load the auto-generated consolidation summary for this session."""
    path = _session_summary_file(self._base, session_id)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")

async def save_session_summary(self, session_id: str, content: str) -> None:
    """Overwrite the session consolidation summary."""
    path = _session_summary_file(self._base, session_id)
    path.write_text(content, encoding="utf-8")
```

**Step 3: Run adapter tests**

Run: `uv run pytest tests/adapters/persistence/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add squidbot/adapters/persistence/jsonl.py tests/adapters/persistence/test_jsonl_global_memory.py
git commit -m "feat(adapters): implement global memory and session summary in JsonlMemory"
```

---

### Task 3: Update `MemoryManager` to use new storage methods

**Files:**
- Modify: `squidbot/core/memory.py`
- Modify: `tests/core/test_memory.py`

**Step 1: Update failing tests**

Update existing tests that reference `load_memory_doc`:

- `test_build_messages_includes_memory_doc` → already renamed to `test_build_messages_includes_global_memory` in Task 1
- `test_consolidation_triggered_above_threshold`: change `load_memory_doc` → `load_session_summary`
- `test_consolidation_appends_to_existing_memory_doc`: rewrite to use `save_session_summary` / `load_session_summary`
- `test_consolidation_summary_appears_in_system_prompt`: no change to assertion — just confirm global memory AND session summary both appear
- `test_consolidation_skipped_when_no_llm`: change `load_memory_doc` → `load_session_summary`

Add new tests:

```python
async def test_build_messages_includes_session_summary(manager, storage):
    await storage.save_session_summary("cli:local", "Session recap: discussed Rust.")
    messages = await manager.build_messages(
        session_id="cli:local",
        system_prompt="You are a bot.",
        user_message="Hello",
    )
    assert "Session recap: discussed Rust." in messages[0].content


async def test_build_messages_global_memory_and_session_summary_both_injected(manager, storage):
    await storage.save_global_memory("User likes Python.")
    await storage.save_session_summary("cli:local", "Discussed async patterns.")
    messages = await manager.build_messages(
        session_id="cli:local",
        system_prompt="You are a bot.",
        user_message="Hello",
    )
    sys_content = messages[0].content
    assert "User likes Python." in sys_content
    assert "Discussed async patterns." in sys_content


async def test_memory_write_does_not_affect_session_summary(storage):
    """Saving global memory does not touch session summary."""
    llm = ScriptedLLM("Summary: new content.")
    manager = MemoryManager(
        storage=storage,
        consolidation_threshold=3,
        keep_recent_ratio=0.34,
        llm=llm,
    )
    await storage.save_global_memory("pre-existing global fact")
    for i in range(4):
        await storage.append_message("s1", Message(role="user", content=f"msg {i}"))
    await manager.build_messages("s1", "sys", "new")
    # Global memory unchanged
    assert await storage.load_global_memory() == "pre-existing global fact"
    # Session summary has the new consolidation
    assert "Summary: new content." in await storage.load_session_summary("s1")
```

Run: `uv run pytest tests/core/test_memory.py -v`
Expected: Several FAIL (methods still call old API)

**Step 2: Update `MemoryManager.build_messages()`**

In `squidbot/core/memory.py`, replace:

```python
memory_doc = await self._storage.load_memory_doc(session_id)
```

with:

```python
global_memory = await self._storage.load_global_memory()
session_summary = await self._storage.load_session_summary(session_id)
```

Replace:

```python
full_system = system_prompt
if memory_doc.strip():
    full_system += f"\n\n## Your Memory\n\n{memory_doc}"
```

with:

```python
full_system = system_prompt
if global_memory.strip():
    full_system += f"\n\n## Your Memory\n\n{global_memory}"
if session_summary.strip():
    full_system += f"\n\n## Conversation Summary\n\n{session_summary}"
```

Remove the reload after consolidation:

```python
# REMOVE THIS LINE:
memory_doc = await self._storage.load_memory_doc(session_id)
```

(Consolidation now writes to session summary, which is loaded separately — no reload needed.)

**Step 3: Update `MemoryManager._consolidate()`**

Replace references to `load_memory_doc` / `save_memory_doc` with `load_session_summary` / `save_session_summary`:

```python
existing = await self._storage.load_session_summary(session_id)
updated = f"{existing}\n\n{summary}" if existing.strip() else summary
await self._storage.save_session_summary(session_id, updated)
```

**Step 4: Run all core tests**

Run: `uv run pytest tests/core/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "feat(core): MemoryManager uses global_memory + session_summary"
```

---

### Task 4: Update `MemoryWriteTool` to write global memory

**Files:**
- Modify: `squidbot/adapters/tools/memory_write.py`
- Modify or create: `tests/adapters/tools/test_memory_write.py`

**Step 1: Check if test file exists**

If `tests/adapters/tools/test_memory_write.py` doesn't exist, create it.

**Step 2: Write failing test**

```python
"""Tests for MemoryWriteTool."""

from __future__ import annotations

import pytest

from squidbot.adapters.tools.memory_write import MemoryWriteTool


class FakeStorage:
    def __init__(self):
        self._global = ""
        self._summaries: dict[str, str] = {}

    async def load_global_memory(self) -> str:
        return self._global

    async def save_global_memory(self, content: str) -> None:
        self._global = content

    async def load_session_summary(self, session_id: str) -> str:
        return self._summaries.get(session_id, "")

    async def save_session_summary(self, session_id: str, content: str) -> None:
        self._summaries[session_id] = content

    async def load_cron_jobs(self): return []
    async def save_cron_jobs(self, jobs): pass
    async def load_history(self, sid): return []
    async def append_message(self, sid, msg): pass
    async def load_consolidated_cursor(self, sid): return 0
    async def save_consolidated_cursor(self, sid, cursor): pass


async def test_memory_write_updates_global_memory():
    storage = FakeStorage()
    tool = MemoryWriteTool(storage=storage, session_id="cli:local")
    result = await tool.execute(content="User likes Rust.")
    assert not result.is_error
    assert await storage.load_global_memory() == "User likes Rust."


async def test_memory_write_does_not_touch_session_summary():
    storage = FakeStorage()
    await storage.save_session_summary("cli:local", "existing summary")
    tool = MemoryWriteTool(storage=storage, session_id="cli:local")
    await tool.execute(content="new global content")
    # Session summary untouched
    assert await storage.load_session_summary("cli:local") == "existing summary"


async def test_memory_write_requires_content():
    storage = FakeStorage()
    tool = MemoryWriteTool(storage=storage, session_id="cli:local")
    result = await tool.execute()
    assert result.is_error
```

Run: `uv run pytest tests/adapters/tools/test_memory_write.py -v`
Expected: FAIL — tool still calls `save_memory_doc`

**Step 3: Update `MemoryWriteTool`**

In `squidbot/adapters/tools/memory_write.py`:

Update description:

```python
description = (
    "Update your long-term memory. This is a global document shared across all "
    "sessions — use it to persist user preferences, ongoing projects, and key facts. "
    "The content REPLACES the current memory document entirely. Keep it concise (≤300 words)."
)
```

Update `execute()`: replace `save_memory_doc` with `save_global_memory`:

```python
await self._storage.save_global_memory(content)
```

The `session_id` is still accepted in `__init__` (needed by the `extra_tools` wiring in
`main.py`) but no longer used. Keep it to avoid touching `main.py` in this task.

**Step 4: Run tool tests**

Run: `uv run pytest tests/adapters/tools/test_memory_write.py -v`
Expected: All PASS

**Step 5: Run full suite + lint + mypy**

```bash
uv run pytest -v
uv run ruff check .
uv run mypy squidbot/
```
Expected: All PASS

**Step 6: Commit**

```bash
git add squidbot/adapters/tools/memory_write.py tests/adapters/tools/test_memory_write.py
git commit -m "feat(tools): memory_write writes to global MEMORY.md"
```
