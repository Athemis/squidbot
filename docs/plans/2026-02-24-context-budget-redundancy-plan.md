# Context Budget and Redundancy Control Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Keep per-turn LLM context compact and non-redundant by introducing explicit context budgets and deterministic de-duplication between Memory and Conversation Summary.

**Architecture:** `MemoryManager.build_messages()` remains the single place that assembles prompt context, but it now applies per-block word budgets and removes overlapping summary lines already present in `MEMORY.md`. Configuration lives in `AgentConfig` so behavior is tunable without code edits. Consolidation logic and storage format stay unchanged.

**Tech Stack:** Python 3.14, Pydantic v2, pytest, ruff, mypy.

**Design doc:** `docs/plans/2026-02-24-context-budget-redundancy-design.md`

---

### Task 1: Add context budget settings to config

**Files:**
- Modify: `squidbot/config/schema.py`
- Test: `tests/core/test_config.py`

**Step 1: Write the failing tests**

In `tests/core/test_config.py`, add:

```python
def test_context_budget_defaults() -> None:
    cfg = AgentConfig()
    assert cfg.context_memory_max_words == 300
    assert cfg.context_summary_max_words == 500
    assert cfg.context_history_max_words == 2500
    assert cfg.context_dedupe_summary_against_memory is True


def test_context_budget_values_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        AgentConfig(context_memory_max_words=0)
    with pytest.raises(ValidationError):
        AgentConfig(context_summary_max_words=-1)
    with pytest.raises(ValidationError):
        AgentConfig(context_history_max_words=0)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_config.py::test_context_budget_defaults -v`
Expected: FAIL (`AgentConfig` missing new fields)

**Step 3: Implement minimal config fields and validation**

In `squidbot/config/schema.py` under `AgentConfig`, add:

```python
context_memory_max_words: int = 300
context_summary_max_words: int = 500
context_history_max_words: int = 2500
context_dedupe_summary_against_memory: bool = True
```

Extend `_validate_consolidation()`:

```python
if self.context_memory_max_words <= 0:
    raise ValueError("agents.context_memory_max_words must be > 0")
if self.context_summary_max_words <= 0:
    raise ValueError("agents.context_summary_max_words must be > 0")
if self.context_history_max_words <= 0:
    raise ValueError("agents.context_history_max_words must be > 0")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add squidbot/config/schema.py tests/core/test_config.py
git commit -m "feat(config): add context budget settings for memory assembly"
```

---

### Task 2: Add failing memory tests for de-duplication and budgets

**Files:**
- Modify: `tests/core/test_memory.py`

**Step 1: Write failing tests**

Add tests:

```python
async def test_build_messages_dedupes_summary_lines_present_in_memory(
    storage: InMemoryStorage,
) -> None:
    await storage.save_global_memory("- user prefers pytest\n- timezone: Europe/Berlin")
    await storage.save_global_summary(
        "- user prefers pytest\n- discussed release checklist"
    )
    manager = MemoryManager(storage=storage)

    messages = await manager.build_messages("cli", "local", "next?", "sys")
    system = messages[0].content
    assert system.count("user prefers pytest") == 1
    assert "discussed release checklist" in system


async def test_build_messages_caps_memory_and_summary_sections(
    storage: InMemoryStorage,
) -> None:
    long_memory = " ".join(["mem"] * 1000)
    long_summary = " ".join(["sum"] * 1000)
    await storage.save_global_memory(long_memory)
    await storage.save_global_summary(long_summary)

    manager = MemoryManager(storage=storage)
    messages = await manager.build_messages("cli", "local", "hello", "sys")
    system = messages[0].content
    assert system.count(" mem") < 1000
    assert system.count(" sum") < 1000


async def test_build_messages_caps_history_by_word_budget_recent_first(
    storage: InMemoryStorage,
) -> None:
    for i in range(30):
        storage._history.append(Message(role="user", content=f"topic-{i} " * 30))
    manager = MemoryManager(storage=storage)

    messages = await manager.build_messages("cli", "local", "latest", "sys")
    history_payload = "\n".join(m.content for m in messages[1:-1])
    assert "topic-29" in history_payload
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_memory.py -k "dedupes_summary or caps_memory or caps_history" -v`
Expected: FAIL (behavior not implemented)

**Step 3: Commit failing tests**

```bash
git add tests/core/test_memory.py
git commit -m "test(memory): add failing tests for context dedupe and budgets"
```

---

### Task 3: Implement deterministic text budget helpers in `MemoryManager`

**Files:**
- Modify: `squidbot/core/memory.py`
- Test: `tests/core/test_memory.py`

**Step 1: Implement minimal helpers**

Add private helpers in `MemoryManager`:

```python
def _truncate_words(self, text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _dedupe_summary_against_memory(self, memory: str, summary: str) -> str:
    memory_lines = {line.strip().lower() for line in memory.splitlines() if line.strip()}
    kept: list[str] = []
    for line in summary.splitlines():
        norm = line.strip().lower()
        if not norm or norm in memory_lines:
            continue
        kept.append(line)
    return "\n".join(kept)


def _take_recent_history_by_word_budget(self, history: list[Message], max_words: int) -> list[Message]:
    kept_rev: list[Message] = []
    used = 0
    for msg in reversed(history):
        cost = len(msg.content.split())
        if kept_rev and used + cost > max_words:
            break
        kept_rev.append(msg)
        used += cost
    return list(reversed(kept_rev))
```

**Step 2: Wire helpers into `build_messages()`**

Apply in this order:
1. load raw `global_memory` and `global_summary`
2. optionally de-dupe summary vs memory (config flag)
3. truncate memory and summary to per-block budgets
4. label history then apply history word budget (recent-first)

Minimal integration sketch:

```python
if self._context_dedupe_summary_against_memory:
    global_summary = self._dedupe_summary_against_memory(global_memory, global_summary)

global_memory = self._truncate_words(global_memory, self._context_memory_max_words)
global_summary = self._truncate_words(global_summary, self._context_summary_max_words)

labelled_history = [self._label_message(msg) for msg in history]
labelled_history = self._take_recent_history_by_word_budget(
    labelled_history,
    self._context_history_max_words,
)
```

**Step 3: Run targeted tests**

Run: `uv run pytest tests/core/test_memory.py -k "dedupes_summary or caps_memory or caps_history" -v`
Expected: PASS

**Step 4: Run full memory tests**

Run: `uv run pytest tests/core/test_memory.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "fix(memory): enforce context budgets and summary-memory dedupe"
```

---

### Task 4: Wire settings through composition root

**Files:**
- Modify: `squidbot/cli/main.py`
- Test: `tests/adapters/test_llm_wiring.py`

**Step 1: Write failing wiring test**

In `tests/adapters/test_llm_wiring.py`, assert `_make_agent_loop()` passes new config values to `MemoryManager` constructor.

**Step 2: Run test to verify failure**

Run: `uv run pytest tests/adapters/test_llm_wiring.py -v`
Expected: FAIL (new args not passed)

**Step 3: Implement wiring**

In `squidbot/cli/main.py` (`_make_agent_loop()`), add:

```python
context_memory_max_words=settings.agents.context_memory_max_words,
context_summary_max_words=settings.agents.context_summary_max_words,
context_history_max_words=settings.agents.context_history_max_words,
context_dedupe_summary_against_memory=settings.agents.context_dedupe_summary_against_memory,
```

Also add constructor parameters to `MemoryManager.__init__` and assign them to instance attrs.

**Step 4: Run tests**

Run: `uv run pytest tests/adapters/test_llm_wiring.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add squidbot/cli/main.py squidbot/core/memory.py tests/adapters/test_llm_wiring.py
git commit -m "refactor(memory): make context budget behavior configurable"
```

---

### Task 5: Update docs for new context controls

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

**Step 1: Update README config example**

Add new `agents.*` options and short explanations:

```yaml
agents:
  consolidation_threshold: 100
  keep_recent_ratio: 0.2
  context_memory_max_words: 300
  context_summary_max_words: 500
  context_history_max_words: 2500
  context_dedupe_summary_against_memory: true
```

**Step 2: Update architecture guidance**

In `AGENTS.md`, document that `MemoryManager` applies context compaction and de-duplication before LLM calls.

**Step 3: Run lint**

Run: `uv run ruff check .`
Expected: PASS

**Step 4: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs(memory): document context budget and dedupe controls"
```

---

### Task 6: Final verification and PR

**Files:**
- Review: `squidbot/core/memory.py`
- Review: `squidbot/config/schema.py`
- Review: `squidbot/cli/main.py`

**Step 1: Run full verification**

```bash
uv run ruff check .
uv run mypy squidbot/
uv run pytest
```

Expected: all pass.

**Step 2: Validate behavior manually (optional smoke check)**

Run:

```bash
squidbot agent -m "Summarize what you know about my preferences."
```

Confirm prompt assembly remains coherent and no duplicated obvious facts appear repeatedly.

**Step 3: Open PR linked to issue #2 follow-up context**

PR title:

```text
fix(memory): reduce prompt redundancy with context budgets and dedupe
```

PR body should include:
- what was deduped
- budget defaults
- why this is a pre-token-budget mitigation
- note that true token budgeting remains tracked by #2
