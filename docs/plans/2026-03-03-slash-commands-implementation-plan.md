# Cross-Channel Minimal Slash Commands Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a minimal cross-channel slash command layer with `/help` and `/new`, where `/new` starts a fresh logical session without automatic history backfill.

**Architecture:** `AgentLoop` handles slash commands centrally via a new core router and maintains logical session generations per physical session. `MemoryManager` accepts a logical `session_id` and `load_history` flag to control implicit history injection. Message persistence includes optional `session_id` for robust session-scoped filtering.

**Tech Stack:** Python 3.14, pytest, ruff, mypy --strict.

---

## Task 1: Add failing tests for slash command behavior

**Files:**
- Modify: `tests/core/test_agent.py`
- Modify: `tests/core/test_memory.py`
- Modify: `tests/adapters/persistence/test_jsonl.py`

**Step 1: Write failing tests**
- Add test that `/help` returns command list and does not consume an LLM response.
- Add test that `/new` returns confirmation and does not consume an LLM response.
- Add memory tests for logical-session filtering and `load_history=False` behavior.
- Add jsonl test ensuring `session_id` serializes/deserializes.

**Step 2: Run targeted tests to verify RED**

Run:
`uv run pytest tests/core/test_agent.py tests/core/test_memory.py tests/adapters/persistence/test_jsonl.py -v`

Expected:
- Failures due to missing slash handling, reset behavior, and message `session_id` support.

## Task 2: Implement minimal command and reset plumbing

**Files:**
- Create: `squidbot/core/slash_commands.py`
- Modify: `squidbot/core/models.py`
- Modify: `squidbot/adapters/persistence/jsonl.py`
- Modify: `squidbot/core/memory.py`
- Modify: `squidbot/core/agent.py`

**Step 1: Add slash command router**
- Parse slash command strings.
- Implement `/help` and `/new` handlers.
- Return structured command result (`handled`, `response_text`, `reset_requested`).

**Step 2: Wire `AgentLoop` command fast path**
- Detect slash commands for string input only.
- Send direct response via channel and return before typing/LLM.
- On `/new`, increment logical session generation and set one-shot `load_history=False` for the next turn.

**Step 3: Add session-aware history selection in memory**
- Add optional `session_id` and `load_history` args to `build_messages(...)`.
- Filter history to rows matching the logical `session_id`.
- Keep legacy fallback matching limited to the base physical session ID.

**Step 4: Add optional `session_id` persistence field**
- Add `session_id: str | None` to `Message`.
- Persist `session_id` for user and assistant messages in `persist_exchange(...)`.
- Serialize/deserialize `session_id` in JSONL adapter.

## Task 3: Verify GREEN and quality gates

**Step 1: Re-run targeted tests**

Run:
`uv run pytest tests/core/test_agent.py tests/core/test_memory.py tests/adapters/persistence/test_jsonl.py -v`

Expected:
- All targeted tests pass.

**Step 2: Run full verification**

Run:
- `uv run ruff check .`
- `uv run ruff format . --check`
- `uv run mypy squidbot/`
- `uv run pytest`

Expected:
- All commands succeed with no failures.
