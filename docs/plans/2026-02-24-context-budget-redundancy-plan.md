# Context Budget and Redundancy Control Implementation Plan (v2)

**Goal:** Reduce per-turn prompt bloat and duplication now, while keeping a clean path to token-based
budgeting for issue #2.

**Design source:** `docs/plans/2026-02-24-context-budget-redundancy-design.md`

**Primary issue:** https://github.com/Athemis/squidbot/issues/2  
**Related dependency risk:** https://github.com/Athemis/squidbot/issues/7

## AGENTS.md Compliance Guardrails

- Use a dedicated feature branch (no non-trivial direct commits to `main`).
- Follow TDD strictly: failing test first, then implementation.
- Keep hexagonal boundaries: no adapter imports in `squidbot/core/`.
- Keep phase 1 lightweight: no mandatory tokenizer dependency.
- Before completion: run `uv run ruff check .`, `uv run mypy squidbot/`, `uv run pytest`.

## Milestones

- **Milestone A (Phase 1):** word budgets + deterministic de-duplication + invariants.
- **Milestone B (Phase 2):** optional tokens mode with graceful fallback (issue #2 closure candidate).

---

## Task 0: Preconditions and Branch Setup

**Files:** none

1. Create branch: `feat/context-budget-redundancy-v2`.
2. Confirm target branch already includes issue #7 fix (or rebase/cherry-pick it first).
3. Run baseline checks once to confirm clean start:
   - `uv run ruff check .`
   - `uv run mypy squidbot/`
   - `uv run pytest`

---

## Task 1: Add Config Fields and Validation (Failing Tests First)

**Files:**
- Modify: `tests/core/test_config.py`
- Modify: `squidbot/config/schema.py`

### 1.1 Add failing tests in `tests/core/test_config.py`

Add tests for:

- defaults of:
  - `context_budget_mode == "words"`
  - `context_memory_max_words == 300`
  - `context_summary_max_words == 500`
  - `context_history_max_words == 2500`
  - `context_total_max_words == 4500`
  - `context_dedupe_summary_against_memory is True`
  - `context_min_recent_messages == 2`
- invalid values:
  - each max words <= 0
  - `context_min_recent_messages <= 0`
  - invalid mode string
  - `context_total_max_words < context_history_max_words`

### 1.2 Verify tests fail

Run:

```bash
uv run pytest tests/core/test_config.py -k "context_budget" -v
```

### 1.3 Implement config fields/validation

In `AgentConfig`, add fields and extend validator with explicit error messages.

### 1.4 Re-run config tests

```bash
uv run pytest tests/core/test_config.py -v
```

---

## Task 2: Add Memory Budget + Dedupe Tests (Strong Assertions)

**Files:**
- Modify: `tests/core/test_memory.py`

### 2.1 Add failing tests

Add tests for:

1. summary lines duplicated in memory are removed after normalization
2. non-duplicated summary lines remain
3. memory and summary are truncated to exact max-word limits
4. history budget keeps newest entries, excludes older ones when over budget
5. history result remains chronological
6. newest message is always retained
7. minimum recent-message floor is respected
8. total budget trim order (`history -> summary -> memory`)

Avoid weak assertions like substring count heuristics; assert concrete word counts and inclusion/exclusion.

### 2.2 Verify failures

```bash
uv run pytest tests/core/test_memory.py -k "dedupe or budget or recent" -v
```

### 2.3 Commit failing tests

```bash
git add tests/core/test_memory.py
git commit -m "test(memory): add failing coverage for context budgets and dedupe invariants"
```

---

## Task 3: Implement Phase 1 in `MemoryManager`

**Files:**
- Modify: `squidbot/core/memory.py`

### 3.1 Implement helpers

Add private helpers with docstrings:

- normalization for dedupe
- word truncation helper
- recent-first history budgeting helper
- total budget enforcement helper

### 3.2 Wire pipeline in `build_messages()`

Apply the deterministic order from design:

1. load raw memory/summary/history
2. optional dedupe summary against memory
3. truncate memory/summary
4. label history
5. budget history with floor
6. enforce total budget order
7. build final messages

### 3.3 Run targeted tests

```bash
uv run pytest tests/core/test_memory.py -k "dedupe or budget or recent" -v
uv run pytest tests/core/test_memory.py -v
```

### 3.4 Commit

```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "fix(memory): apply deterministic context budgets and summary dedupe"
```

---

## Task 4: Wire New Config Through Composition Root

**Files:**
- Modify: `tests/adapters/test_llm_wiring.py`
- Modify: `squidbot/cli/main.py`

### 4.1 Add failing wiring tests

Assert `_make_agent_loop()` passes all new `AgentConfig` context fields into `MemoryManager`.

### 4.2 Verify failure

```bash
uv run pytest tests/adapters/test_llm_wiring.py -v
```

### 4.3 Implement wiring in `cli/main.py`

Pass the full context config set into `MemoryManager(...)`.

### 4.4 Re-run wiring tests

```bash
uv run pytest tests/adapters/test_llm_wiring.py -v
```

### 4.5 Commit

```bash
git add squidbot/cli/main.py tests/adapters/test_llm_wiring.py
git commit -m "refactor(cli): wire context budget settings into memory manager"
```

---

## Task 5: Phase 2 Scaffold for Optional Tokens Mode

**Files:**
- Modify: `tests/core/test_memory.py`
- Modify: `squidbot/core/memory.py`
- Modify: `squidbot/cli/main.py`

### 5.1 Add failing fallback tests

Cases:

- `context_budget_mode="tokens"` and no token counter -> falls back to words mode
- single warning is logged
- no runtime failure

### 5.2 Implement minimal scaffold

- Add mode handling in `MemoryManager`.
- Keep words mode as primary implementation.
- If tokens requested and unavailable, fallback deterministically.

No tokenizer dependency is added in this task.

### 5.3 Run tests and commit

```bash
uv run pytest tests/core/test_memory.py -k "tokens or fallback" -v
```

```bash
git add squidbot/core/memory.py squidbot/cli/main.py tests/core/test_memory.py
git commit -m "feat(memory): add optional token budget mode with safe words fallback"
```

---

## Task 6: Documentation Updates

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md` (only if architecture behavior documentation needs update)

Add concise docs for new context settings, defaults, and token-mode fallback semantics.

Commit:

```bash
git add README.md AGENTS.md
git commit -m "docs(memory): document context budget controls and token-mode fallback"
```

---

## Task 7: Final Verification and PR

Run full verification:

```bash
uv run ruff check .
uv run mypy squidbot/
uv run pytest
```

PR title:

```text
fix(memory): reduce prompt redundancy with deterministic context budgets
```

PR checklist:

- summarizes invariants introduced
- clarifies issue #2 status:
  - if only Phase 1 landed: keep #2 open as partially mitigated
  - if token mode behavior is complete and tested: close #2
- includes verification command outputs
