# Memory System Improvements (Performance, Resilience, Reliability)

## TL;DR
> **Summary**: Harden JSONL/Markdown persistence and history search so the agent keeps running under corruption/partial writes, while reducing unnecessary memory/IO load — without adding new subsystems.
> **Deliverables**: (1) resilient `JsonlMemory` I/O + parsing, (2) streaming `search_history`, (3) AgentLoop memory error boundaries, (4) expanded tests.
> **Effort**: Medium
> **Parallel**: YES — 2 waves + final verification
> **Critical Path**: 1 (JsonlMemory hardening) → 3 (search_history streaming) → 4 (full suite verification)

## Context
### Original Request
"Verbesserungen am Memory-System: Performanz, Resilienz, Zuverlaessigkeit. Dabei aber den Use-Case im Auge behalten: kein YAGNI!"

### Interview Summary
- No new features requested; improve robustness/perf of existing global manual-only memory model.
- Defaults applied (no user input required): keep behavior stable; prefer minimal algorithmic improvements over new config knobs.

### Repo Reality (grounded)
- `MemoryManager` builds each LLM call from system prompt + global `workspace/MEMORY.md` + last N `history.jsonl` messages; persists user+assistant exchanges only.
  - Reference: `squidbot/core/memory.py:117-195`
- `JsonlMemory.load_history()` currently reads the entire `history.jsonl` via `read_text().splitlines()` then slices for `last_n`.
  - Reference: `squidbot/adapters/persistence/jsonl.py:107-126`
- `JsonlMemory.append_message()` uses `fcntl.flock` and runs in `asyncio.to_thread`.
  - Reference: `squidbot/adapters/persistence/jsonl.py:128-147`
- `search_history` currently loads all messages into memory before searching.
  - Reference: `squidbot/adapters/tools/search_history.py:157-191`
- There is solid test coverage for the current model; gaps are corruption tolerance and memory failure boundaries.
  - References: `tests/core/test_memory.py`, `tests/core/test_agent.py`, `tests/adapters/persistence/test_jsonl.py`, `tests/adapters/tools/test_search_history.py`

### Oracle Review (gaps addressed)
- Prefer `deque(maxlen=last_n)` streaming read over “tail-reading” tricks (correctness first).
- Preserve `search_history` ordering semantics (earliest matches first) and context behavior.
- Add atomic replace for whole-file writes (`MEMORY.md`, `cron/jobs.json`).

### Metis Review (gaps addressed)
- Guard against scope creep (no DB, no indexing service, no complex retries).
- Add explicit degraded-mode behavior: continue without history/memory on read errors; do not crash.

## Work Objectives
### Core Objective
Make memory persistence and recall robust against partial writes, corruption, and filesystem errors, while reducing avoidable IO and memory usage.

### Deliverables
- `JsonlMemory` reads/writes are non-blocking (via `asyncio.to_thread`) and resilient to malformed/partial JSONL lines.
- Whole-file saves (`MEMORY.md`, `cron/jobs.json`) are atomic (temp + `os.replace`) to avoid truncation/corruption.
- `SearchHistoryTool` scans `history.jsonl` in one pass (no full-history load), preserves output semantics.
- `AgentLoop` continues in degraded mode when memory building/persisting fails.
- Tests cover corruption handling and degraded mode.

### Definition of Done (agent-executable)
- `uv run ruff check .`
- `uv run mypy squidbot/`
- `uv run pytest`

### Must Have
- No new dependencies.
- No change to the high-level model: global `history.jsonl` + global `workspace/MEMORY.md` + explicit recall via `search_history`.
- Preserve `search_history` output format and ordering (compat behavior).

### Must NOT Have (No-YAGNI guardrails)
- No embeddings/vector search.
- No SQLite/DB migration.
- No background indexing, rotation, compression, or summarization.
- No new “health check” daemon / circuit breaker / retry framework; only local try/except boundaries.

## Verification Strategy
> ZERO HUMAN INTERVENTION — all verification is agent-executed.
- Test decision: tests-after (refactor hardening) using existing pytest suite.
- Evidence: store command outputs in `.sisyphus/evidence/` (executor responsibility).

## Execution Strategy
### Parallel Execution Waves
Wave 1 (foundation + independent):
- 1. JsonlMemory hardening + atomic writes + tests
- 2. AgentLoop degraded-mode boundaries + tests

Wave 2 (depends on Wave 1 parsing helpers):
- 3. Streaming `search_history` implementation + tests

Wave 3:
- 4. Full verification + final review wave

### Dependency Matrix (full)
- Task 1 blocks Task 3 (shared parsing + reliable history reads)
- Task 2 is independent of 1/3 (core error boundary)
- Task 4 depends on 1–3

### Agent Dispatch Summary
- Wave 1: 2 agents (`unspecified-high` x2)
- Wave 2: 1 agent (`unspecified-high`)
- Wave 3: 4 agents (review wave)

## TODOs
> Implementation + Test = ONE task. Never separate.

- [x] 1. Harden `JsonlMemory` (streaming reads, safe parsing, atomic whole-file writes)

  **What to do**:
  - Update `squidbot/adapters/persistence/jsonl.py`:
    - Use `from loguru import logger` and:
      - In `load_history(...)`, log a single WARNING summary when any lines are skipped (count + first error preview).
      - In `load_cron_jobs()`, log a WARNING when JSON decoding fails and return `[]`.
    - Add a safe, line-by-line JSONL parse helper (e.g., `deserialize_message_safe(...) -> Message | None`) that:
      - Skips blank lines.
      - Catches JSON decode errors and returns `None`.
      - Tolerates invalid UTF-8 by reading in binary and decoding per-line with `errors="replace"` (or equivalent), then JSON parsing.
    - Rewrite `load_history(last_n=...)` to avoid `read_text().splitlines()`:
      - Run file IO in `asyncio.to_thread`.
      - Stream-scan the file.
      - If `last_n is None`: return all valid messages in chronological order.
      - If `last_n` provided: use `collections.deque(maxlen=last_n)` to keep last N *valid* messages in chronological order.
      - Use `fcntl.flock(f, LOCK_SH)` while reading (try/finally unlock). If locking fails unexpectedly, continue without a read lock.
    - Make `load_global_memory()` and `load_cron_jobs()` run in `asyncio.to_thread` and be error-tolerant:
      - Missing files: return empty (`""` / `[]`).
      - JSON decode errors in cron jobs: return `[]` and log a warning via `loguru`.
    - Make `save_global_memory()` and `save_cron_jobs()` atomic:
      - Write temp file in same directory.
      - `flush` + `os.fsync` (temp file only).
      - `os.replace(temp, target)`.
      - Run in `asyncio.to_thread`.
  - Expand tests:
    - `tests/adapters/persistence/test_jsonl.py`: add tests that malformed JSONL lines are skipped, and `last_n` returns the last N valid messages.
    - Add a test that invalid bytes in `history.jsonl` do not crash `load_history`.
    - `tests/adapters/persistence/test_jsonl_global_memory.py`: keep existing roundtrip; add a regression test that `save_global_memory` works when parent dirs don’t exist (already asserted indirectly; keep stable).

  **Must NOT do**:
  - Do not change `MemoryPort`.
  - Do not add new config knobs.
  - Do not attempt fancy tail-reading / seeking unless a measured need exists.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` — cross-cutting persistence + tests.
  - Skills: none.

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: 3 | Blocked By: none

  **References**:
  - Existing load_history (whole-file read): `squidbot/adapters/persistence/jsonl.py:107-126`
  - Existing append lock pattern: `squidbot/adapters/persistence/jsonl.py:128-147`
  - SearchHistory depends on history format: `squidbot/adapters/tools/search_history.py:18-103`
  - Tests patterns with `tmp_path`: `tests/adapters/persistence/test_jsonl.py`, `tests/adapters/persistence/test_jsonl_global_memory.py`

  **Acceptance Criteria**:
  - [ ] `uv run pytest tests/adapters/persistence/test_jsonl.py -v` passes.
  - [ ] `uv run pytest tests/adapters/persistence/test_jsonl_global_memory.py -v` passes.
  - [ ] New tests demonstrate: one malformed JSONL line does not prevent loading subsequent valid messages.

  **QA Scenarios**:
  ```
  Scenario: Malformed JSONL line is skipped
    Tool: Bash
    Steps:
      1) uv run pytest tests/adapters/persistence/test_jsonl.py -k "malformed" -v
    Expected: PASS; load_history returns valid messages only
    Evidence: .sisyphus/evidence/task-1-jsonl-malformed.txt

  Scenario: Invalid UTF-8 bytes do not crash history load
    Tool: Bash
    Steps:
      1) uv run pytest tests/adapters/persistence/test_jsonl.py -k "utf" -v
    Expected: PASS
    Evidence: .sisyphus/evidence/task-1-jsonl-utf8.txt
  ```

  **Commit**: YES | Message: `fix(persistence): make history and cron IO resilient` | Files: `squidbot/adapters/persistence/jsonl.py`, `tests/adapters/persistence/test_jsonl.py`, `tests/adapters/persistence/test_jsonl_global_memory.py`

- [x] 2. Add AgentLoop degraded-mode boundaries for memory failures

  **What to do**:
  - Update `squidbot/core/agent.py`:
    - Wrap `self._memory.build_messages(...)` in try/except.
    - On exception: build a minimal message list with the existing system prompt and the current user message:
      - `Message(role="system", content=self._system_prompt)`
      - `Message(role="user", content=user_message)`
    - Continue the run; do not crash the loop.
    - Wrap `self._memory.persist_exchange(...)` in try/except.
      - On exception: do not crash; still deliver output to channel.
  - Add tests in `tests/core/test_agent.py`:
    - Create a MemoryManager-like stub that raises from `build_messages`.
    - Assert `AgentLoop.run()` still produces a response.
    - Create a stub that raises from `persist_exchange`.
    - Assert `AgentLoop.run()` still produces a response.

  **Must NOT do**:
  - No retries/backoff loops.
  - No new persistent “error state”.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` — core behavior change + tests.
  - Skills: none.

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: none | Blocked By: none

  **References**:
  - Where build_messages is called today: `squidbot/core/agent.py:180-184`
  - Where persist_exchange is called today: `squidbot/core/agent.py:226-232`
  - Current AgentLoop tests/doubles: `tests/core/test_agent.py:26-209`

  **Acceptance Criteria**:
  - [ ] `uv run pytest tests/core/test_agent.py -v` passes.
  - [ ] New tests demonstrate: build_messages failure does not abort the request.
  - [ ] New tests demonstrate: persist_exchange failure does not abort the request.

  **QA Scenarios**:
  ```
  Scenario: build_messages failure still yields response
    Tool: Bash
    Steps:
      1) uv run pytest tests/core/test_agent.py -k "build_messages" -v
    Expected: PASS
    Evidence: .sisyphus/evidence/task-2-agent-degraded-build.txt

  Scenario: persist_exchange failure still yields response
    Tool: Bash
    Steps:
      1) uv run pytest tests/core/test_agent.py -k "persist_exchange" -v
    Expected: PASS
    Evidence: .sisyphus/evidence/task-2-agent-degraded-persist.txt
  ```

  **Commit**: YES | Message: `fix(agent): continue when memory fails` | Files: `squidbot/core/agent.py`, `tests/core/test_agent.py`

- [x] 3. Make `search_history` stream-scan `history.jsonl` (no full load)

  **What to do**:
  - Update `squidbot/adapters/tools/search_history.py` to avoid `JsonlMemory(...).load_history()` for the tool path.
  - Implement a single-pass scan of `history.jsonl`:
    - Preserve current semantics:
      - earliest matches first (chronological scan; stop after `max_results` matches *and* capture +1 context for the last match).
      - search is case-insensitive substring match (use `.lower()` as today).
      - apply `days` cutoff (skip messages older than cutoff).
      - only `SEARCHABLE_ROLES = ("user", "assistant")` are eligible for matching and output (keep existing).
      - context window remains “adjacent messages by position” (±1 in stream) and still filtered by searchable role + non-empty content.
    - Use the safe JSONL parsing helper from Task 1 (import from `squidbot.adapters.persistence.jsonl`).
    - Run file IO in `asyncio.to_thread`.
    - Exact streaming algorithm (must preserve current output semantics):
      - Maintain `prev: Message | None` as the immediately previous parsed message (any role).
      - When the current message is a match-eligible message and contains the query, record a `MatchContext` containing:
        - `before = prev` (may be None)
        - `hit = current`
        - `after = None` initially
      - After recording a match, set a `capture_next_for_last_match = True` flag.
      - On the next successfully parsed message (even if not searchable), if `capture_next_for_last_match` is True, set `after` for the most recent recorded match to that message, then set the flag False.
      - Stop scanning only when:
        - you have recorded `max_results` matches, AND
        - `capture_next_for_last_match` is False (so +1 context has been captured), OR end-of-file.
      - While formatting results, include `before/hit/after` lines only if they are in `SEARCHABLE_ROLES` and have non-empty `content` (same filter as today).
  - Update tests in `tests/adapters/tools/test_search_history.py` only if needed (behavior should remain stable).
  - Add a new test to ensure a malformed line in `history.jsonl` does not crash `search_history`.

  **Must NOT do**:
  - No new search index.
  - No regex search.
  - No new tool parameters.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` — tool behavior refactor with careful compat.
  - Skills: none.

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: none | Blocked By: 1

  **References**:
  - Current tool logic (loads all history): `squidbot/adapters/tools/search_history.py:157-191`
  - Output formatting & truncation constraints: `squidbot/adapters/tools/search_history.py:69-103`
  - Existing tests: `tests/adapters/tools/test_search_history.py:33-186`

  **Acceptance Criteria**:
  - [ ] `uv run pytest tests/adapters/tools/test_search_history.py -v` passes.
  - [ ] Added test proves malformed JSONL line does not crash the tool.

  **QA Scenarios**:
  ```
  Scenario: search_history returns matches without full-history load
    Tool: Bash
    Steps:
      1) uv run pytest tests/adapters/tools/test_search_history.py -v
    Expected: PASS
    Evidence: .sisyphus/evidence/task-3-search-history-stream.txt

  Scenario: malformed JSONL line tolerated in search_history
    Tool: Bash
    Steps:
      1) uv run pytest tests/adapters/tools/test_search_history.py -k "malformed" -v
    Expected: PASS
    Evidence: .sisyphus/evidence/task-3-search-history-malformed.txt
  ```

  **Commit**: YES | Message: `refactor(tools): stream-scan history in search_history` | Files: `squidbot/adapters/tools/search_history.py`, `tests/adapters/tools/test_search_history.py`

- [x] 4. Final verification wave (quality + scope)

  **What to do**:
  - Run full checks: `uv run ruff check .`, `uv run mypy squidbot/`, `uv run pytest`.
  - Confirm no new dependencies were added and no config surface expanded.

  **Recommended Agent Profile**:
  - Category: `unspecified-high`
  - Skills: none.

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: none | Blocked By: 1, 2, 3

  **Acceptance Criteria**:
  - [x] `uv run ruff check .` passes.
  - [x] `uv run mypy squidbot/` passes.
  - [x] `uv run pytest` passes.

  **QA Scenarios**:
  ```
  Scenario: Full suite green
    Tool: Bash
    Steps:
      1) uv run ruff check .
      2) uv run mypy squidbot/
      3) uv run pytest
    Expected: All PASS
    Evidence: .sisyphus/evidence/task-4-full-verification.txt
  ```

  **Commit**: NO

## Final Verification Wave (4 parallel agents, ALL must APPROVE)
- [x] F1. Plan Compliance Audit — oracle
- [x] F2. Code Quality Review — unspecified-high
- [x] F3. Reliability/Failure-Mode QA — unspecified-high
- [x] F4. Scope Fidelity Check (no-YAGNI) — deep

## Commit Strategy
- Use Conventional Commits; prefer 1 commit per TODO above.
- Run `uv run ruff check .` and `uv run pytest` before each commit (repo convention).

## Success Criteria
- The agent does not crash when `history.jsonl` contains malformed/partial lines.
- The agent does not crash when reading/writing memory fails; it continues in degraded mode.
- `search_history` can operate on large histories without loading the entire file into memory.
- All tests and static checks pass.
