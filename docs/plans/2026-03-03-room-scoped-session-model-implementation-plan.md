# Room-Scoped Session Model Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Switch Matrix session identity to room-scoped sessions while preserving per-user attribution for persistence and owner-policy checks.

**Architecture:** Matrix adapter emits room-scoped `Session` objects and stores the actual Matrix sender in metadata. Gateway forwards sender attribution into `AgentLoop`, and `MessageTool` uses explicit sender attribution for authorization.

**Tech Stack:** Python 3.14, pytest, ruff, mypy --strict.

**Design doc:** `docs/plans/2026-03-03-room-scoped-session-model-design.md`

---

### Task 1: Add failing tests for new session semantics

**Files:**
- Modify: `tests/adapters/channels/test_matrix.py`
- Modify: `tests/core/test_agent.py`
- Modify: `tests/cli/test_gateway.py`
- Modify: `tests/adapters/tools/test_message.py`

**Step 1: Write failing tests**
- Assert Matrix inbound `session.sender_id == room_id`.
- Assert Matrix inbound metadata includes `matrix_sender_id`.
- Assert `AgentLoop.run(..., user_sender_id=...)` persists that sender ID.
- Assert gateway forwards `matrix_sender_id` into `AgentLoop.run()`.
- Assert `MessageTool` owner checks use explicit current sender attribution.

**Step 2: Run tests to verify RED**
- Run: `uv run pytest tests/adapters/channels/test_matrix.py tests/core/test_agent.py tests/cli/test_gateway.py tests/adapters/tools/test_message.py -v`

**Step 3: Confirm failures are due to missing behavior**
- Expect failures about old sender-scoped session assumptions and missing forwarding args.

### Task 2: Implement minimal production changes

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Modify: `squidbot/cli/gateway.py`
- Modify: `squidbot/core/agent.py`
- Modify: `squidbot/adapters/tools/message.py`

**Step 1: Matrix adapter**
- Create Matrix sessions with room ID as `sender_id`.
- Add `matrix_sender_id` to metadata in text/media/reaction paths.

**Step 2: Agent loop attribution override**
- Add optional `user_sender_id` to `AgentLoop.run(...)`.
- Persist using `user_sender_id` fallbacking to `session.sender_id`.

**Step 3: Gateway forwarding**
- In `_channel_loop` and `_channel_loop_with_state`, pass `user_sender_id` from inbound metadata (`matrix_sender_id` when present).
- Keep defaults unchanged for non-Matrix channels.

**Step 4: MessageTool authorization attribution**
- Add optional `current_sender_id` to `MessageTool` constructor.
- Use this value for owner checks and sender-override comparisons.

### Task 3: Verify GREEN and quality gates

**Step 1: Re-run targeted tests**
- Run: `uv run pytest tests/adapters/channels/test_matrix.py tests/core/test_agent.py tests/cli/test_gateway.py tests/adapters/tools/test_message.py -v`

**Step 2: Run repository checks**
- Run: `uv run ruff check .`
- Run: `uv run ruff format . --check`
- Run: `uv run pytest`

**Step 3: Fix regressions and re-run until clean**
