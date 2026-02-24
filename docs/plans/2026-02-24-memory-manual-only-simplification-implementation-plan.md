# Memory Manual-Only Simplification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace automatic memory consolidation with a manual-only model that keeps global cross-channel history and global `MEMORY.md`, while removing summary/cursor complexity.

**Architecture:** `MemoryManager` becomes a thin context assembler: load `MEMORY.md`, load last `N` global history messages, label history, append user message. Historical deep recall is explicit via `search_history`. Consolidation and cursor APIs are removed end-to-end (ports, adapters, config, tests, docs).

**Tech Stack:** Python 3.14, Pydantic v2, pytest, mypy, ruff.

**Design doc:** `docs/plans/2026-02-24-memory-manual-only-simplification-design.md`

---

### Task 1: Replace consolidation config with a single history window setting

**Files:**
- Modify: `tests/core/test_config.py`
- Modify: `squidbot/config/schema.py`

**Step 1: Write failing tests**

Add tests in `tests/core/test_config.py`:

```python
def test_history_context_messages_default() -> None:
    settings = Settings()
    assert settings.agents.history_context_messages == 80


def test_history_context_messages_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        AgentConfig(history_context_messages=0)
```

Remove or replace tests that assert `consolidation_threshold` and `keep_recent_ratio` defaults.

**Step 2: Run tests to verify RED**

Run: `uv run pytest tests/core/test_config.py -k "history_context_messages or consolidation_defaults" -v`
Expected: FAIL (new field missing and/or old expectations still present).

**Step 3: Implement minimal schema change**

In `squidbot/config/schema.py`:

- Add `history_context_messages: int = 80` to `AgentConfig`.
- Validate `history_context_messages > 0`.
- Remove consolidation-specific fields and validation.

**Step 4: Run tests to verify GREEN**

Run: `uv run pytest tests/core/test_config.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/config/schema.py tests/core/test_config.py
git commit -m "refactor(config): simplify memory settings to history context window"
```

---

### Task 2: Simplify MemoryPort and protocol test doubles

**Files:**
- Modify: `squidbot/core/ports.py`
- Modify: `tests/core/test_ports.py`
- Modify: `tests/core/test_agent.py`

**Step 1: Write failing tests**

In protocol/double tests, remove summary/cursor methods from `MockMemory` and `InMemoryStorage`
classes used to satisfy `MemoryPort`.

**Step 2: Run tests to verify RED**

Run: `uv run pytest tests/core/test_ports.py tests/core/test_agent.py -v`
Expected: FAIL until `MemoryPort` is simplified.

**Step 3: Simplify protocol**

In `squidbot/core/ports.py`, remove:

- `load_global_summary` / `save_global_summary`
- `load_global_cursor` / `save_global_cursor`

Keep history, global memory, and cron methods.

**Step 4: Run tests to verify GREEN**

Run: `uv run pytest tests/core/test_ports.py tests/core/test_agent.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/core/ports.py tests/core/test_ports.py tests/core/test_agent.py
git commit -m "refactor(memory): remove summary and cursor APIs from MemoryPort"
```

---

### Task 3: Remove summary/cursor persistence from JsonlMemory

**Files:**
- Modify: `tests/adapters/persistence/test_jsonl.py`
- Modify: `squidbot/adapters/persistence/jsonl.py`

**Step 1: Write failing tests**

In `tests/adapters/persistence/test_jsonl.py`:

- Delete/replace summary and cursor roundtrip tests.
- Add explicit assertions that history/global-memory behaviors still work.

**Step 2: Run tests to verify RED**

Run: `uv run pytest tests/adapters/persistence/test_jsonl.py -v`
Expected: FAIL while adapter still exposes removed methods or obsolete behavior.

**Step 3: Implement minimal adapter simplification**

In `squidbot/adapters/persistence/jsonl.py`:

- Remove `_global_summary_file` and `_history_meta_file` active usage.
- Remove `load_global_summary` / `save_global_summary`.
- Remove `load_global_cursor` / `save_global_cursor`.

Do not add compatibility wrappers or feature flags.

**Step 4: Run tests to verify GREEN**

Run: `uv run pytest tests/adapters/persistence/test_jsonl.py tests/adapters/persistence/test_jsonl_global_memory.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/adapters/persistence/jsonl.py tests/adapters/persistence/test_jsonl.py
git commit -m "refactor(persistence): drop summary and cursor storage paths"
```

---

### Task 4: Rewrite memory core tests for manual-only behavior

**Files:**
- Modify: `tests/core/test_memory.py`

**Step 1: Write failing tests for new behavior**

Add/keep tests that assert:

1. `build_messages()` includes `## Your Memory` when present.
2. `build_messages()` includes only last `history_context_messages` labelled history items.
3. No conversation summary block is injected.
4. `persist_exchange()` appends exactly user + assistant messages with channel/sender metadata.

Delete consolidation/meta-consolidation/cursor warning tests.

**Step 2: Run tests to verify RED**

Run: `uv run pytest tests/core/test_memory.py -v`
Expected: FAIL until `MemoryManager` implementation is simplified.

**Step 3: Commit failing test rewrite**

```bash
git add tests/core/test_memory.py
git commit -m "test(memory): rewrite expectations for manual-only memory model"
```

---

### Task 5: Simplify MemoryManager implementation

**Files:**
- Modify: `squidbot/core/memory.py`
- Test: `tests/core/test_memory.py`

**Step 1: Implement minimal behavior**

In `MemoryManager`:

- Remove consolidation constants/prompts.
- Remove `_call_llm`, `_maybe_meta_consolidate`, `_consolidate`.
- Remove `llm`, `consolidation_threshold`, `keep_recent_ratio` from constructor.
- Add `history_context_messages` constructor arg (default `80`).
- In `build_messages()`, call `load_history(last_n=self._history_context_messages)`.
- Keep existing owner labeling and skills injection.

**Step 2: Run targeted tests**

Run: `uv run pytest tests/core/test_memory.py -v`
Expected: PASS.

**Step 3: Run dependent core tests**

Run: `uv run pytest tests/core/test_agent.py tests/core/test_ports.py -v`
Expected: PASS.

**Step 4: Commit**

```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "refactor(memory): switch to manual-only context assembly"
```

---

### Task 6: Update composition root wiring

**Files:**
- Modify: `squidbot/cli/main.py`
- Modify: `tests/adapters/test_llm_wiring.py` (or nearest wiring test file)

**Step 1: Write failing wiring test**

Assert `MemoryManager` is constructed with `history_context_messages` and without consolidation/llm
memory params.

**Step 2: Run tests to verify RED**

Run: `uv run pytest tests/adapters/test_llm_wiring.py -v`
Expected: FAIL.

**Step 3: Implement wiring change**

In `_make_agent_loop()` pass only:

```python
history_context_messages=settings.agents.history_context_messages
```

Do not keep transitional option-2 hooks.

**Step 4: Run tests to verify GREEN**

Run: `uv run pytest tests/adapters/test_llm_wiring.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/cli/main.py tests/adapters/test_llm_wiring.py
git commit -m "refactor(cli): wire simplified memory manager configuration"
```

---

### Task 7: Update memory behavior docs and skill guidance

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `squidbot/skills/memory/SKILL.md`

**Step 1: Update docs text**

- Remove references to global summary, cursor, and meta-consolidation.
- Document manual-only model and `search_history` as explicit long-tail recall path.
- Keep statement that history remains global across channels.

**Step 2: Update skill text**

Add explicit guidance:

- keep `MEMORY.md` durable and compact
- use `search_history` when uncertain about older details

**Step 3: Run doc/lint checks**

Run: `uv run ruff check .`
Expected: PASS.

**Step 4: Commit**

```bash
git add README.md AGENTS.md squidbot/skills/memory/SKILL.md
git commit -m "docs(memory): describe manual-only model and explicit history recall"
```

---

### Task 8: Final verification

**Files:**
- Review all modified files above

**Step 1: Type-check**

Run: `uv run mypy squidbot/`
Expected: PASS.

**Step 2: Full test suite**

Run: `uv run pytest`
Expected: PASS.

**Step 3: Final lint**

Run: `uv run ruff check .`
Expected: PASS.

**Step 4: Inspect diff for banned leftovers**

Run: `git grep -n "consolidation\|meta-consolidation\|global_summary\|global_cursor"`
Expected: only historical design docs or intentionally preserved text, no active runtime path.

**Step 5: Prepare PR**

Suggested title:

`refactor(memory): simplify to manual-only global memory + explicit history search`

Suggested summary bullets:

- remove consolidation/cursor systems from core and persistence
- keep global cross-channel history and global MEMORY.md
- make long-tail recall explicit via search_history

---

## Guardrails

- Do not keep Option 2 in code behind flags, TODO hooks, or dead branches.
- Do not alter global history sharing semantics.
- Prefer deletion over abstraction when removing consolidation code.
