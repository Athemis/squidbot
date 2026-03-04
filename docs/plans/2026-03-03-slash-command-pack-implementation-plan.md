# Slash Command Pack v1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship deterministic owner-gated slash commands (`/help`, `/new`, `/status`, `/remember <text>`) with `/status` history count and robust `/remember` error handling.

**Architecture:** Keep parsing in `slash_commands.py`, execution/authorization in `AgentLoop`, and owner/history helpers in `MemoryManager`. Do not ship `/history` as a slash command.

**Tech Stack:** Python 3.14, pytest, ruff, mypy --strict.

---

## Requirement-to-Test Matrix

| Requirement | Tests |
|---|---|
| Slash commands bypass LLM | existing `/help` + `/new` tests plus slash status/remember tests in `tests/core/test_agent.py` |
| CLI slash always allowed | `test_slash_commands_always_allowed_on_cli` |
| Non-CLI slash owner-only | `test_slash_commands_denied_for_non_cli_non_owner` |
| Matrix auth uses metadata sender | `test_slash_matrix_auth_uses_metadata_sender`, `test_slash_matrix_missing_metadata_sender_is_denied` |
| `/status` includes `history_messages` | `test_slash_status_returns_contract_without_llm_call`, `test_slash_status_includes_current_logical_history_size` |
| `/status` deterministic error fallback | `test_slash_status_returns_deterministic_error_when_history_count_fails` |
| `/remember` failure-path resilience | remember failure tests in `tests/core/test_agent.py` |
| `/history` not shipped | parser + agent unknown-command tests |

## Tasks

### Task 1: Parser Contract

**Files:**
- Modify: `squidbot/core/slash_commands.py`
- Test: `tests/core/test_slash_commands.py`

1. Keep `/status` and `/remember` parser actions.
2. Keep `/history` as unknown command.
3. Keep `/remember` usage validation.
4. Run: `uv run pytest tests/core/test_slash_commands.py -v`

### Task 2: Agent Slash Dispatch

**Files:**
- Modify: `squidbot/core/agent.py`
- Modify: `squidbot/core/memory.py`
- Test: `tests/core/test_agent.py`

1. Keep owner authorization policy (CLI allow, non-CLI owner-only).
2. Keep `/status` payload with `history_messages`.
3. Add `/status` local exception containment with deterministic error text.
4. Harden `/remember` invalid tool result handling.
5. Run: `uv run pytest tests/core/test_agent.py -k "slash" -v`

### Task 3: Test Coverage and Docs

**Files:**
- Modify: `tests/core/test_agent.py`
- Modify: `tests/core/test_slash_commands.py`
- Modify: `README.md`

1. Add `/remember` failure-path tests (missing tool, exception, error result, invalid result shape).
2. Keep parser and status tests aligned with current command set.
3. Keep both README command lists synchronized.
4. Run: `uv run pytest tests/core/test_agent.py tests/core/test_slash_commands.py -v`

### Task 4: Full Verification

Run:
- `uv run ruff check .`
- `uv run ruff format . --check`
- `uv run mypy squidbot/`
- `uv run pytest`

All commands must pass before final commit/push.
