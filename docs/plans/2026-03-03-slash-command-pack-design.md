# Cross-Channel Slash Command Pack v1 - Design

## Problem

The current slash-command surface in core is intentionally minimal (`/help`, `/new`).
Daily operation still requires natural-language prompts for deterministic control actions
such as checking session state, recalling older history, and writing memory notes. That
adds avoidable LLM roundtrips and inconsistent behavior in group contexts.

## Goal

Add a deterministic command pack that works identically across CLI, Matrix, and Email:

- `/status` - show current session context state.
- `/history` - show how to recall history (informational command only).
- `/remember <text>` - persist a memory note through existing memory workflow.

All command handling must bypass LLM inference and return immediate responses.

## Scope

### In scope

- Extend core slash-command parsing to support arguments and action metadata.
- Add deterministic handlers for `/status`, `/history`, `/remember`.
- Enforce owner-only authorization policy for all slash commands.
- Keep channel behavior uniform by handling commands only in `AgentLoop`.
- Reuse existing memory-write pathway for `/remember`.
- Add serialization semantics for `/remember` read-modify-write path.
- Add tests for happy paths, validation errors, authorization, and runtime failures.

### Out of scope

- Command flags/options (`--limit`, `--json`, etc.).
- Command aliases (`/mem`, `/find`, etc.).
- Channel-specific parser differences.
- Generalized role/permissions framework beyond this command pack.

## Command Authorization

All slash commands are restricted to the owner:

- Owner-only: `/help`, `/new`, `/status`, `/history`, `/remember`

Owner detection reuses existing owner alias matching already used in memory attribution.
CLI channel is always authorized for slash commands (physical host access implies owner).

If sender attribution is missing or does not match owner policy, slash execution is denied
with deterministic response:

- `Access denied: slash commands are only available to the owner.`

This is command-scoped policy, not a new global permissions subsystem.

## Authoritative Sender Identity

Slash authorization uses a channel-aware actor identity source:

- Non-Matrix channels: `user_sender_id` when provided, otherwise `session.sender_id`.
- Matrix: `outbound_metadata["matrix_sender_id"]` only.

Matrix `session.sender_id` is room-scoped and is not used for owner authorization.
If `matrix_sender_id` is missing/empty, slash commands are denied deterministically.

Auth input precedence is therefore:

1. Matrix channel: metadata sender only.
2. Other channels: explicit `user_sender_id`.
3. Other channels fallback: `session.sender_id`.

## Architecture

### 1) Core command router enhancement

Extend `squidbot/core/slash_commands.py` from command-only parsing to command-plus-args
parsing. The router returns a structured result object including optional action and
argument fields for runtime dispatch.

### 2) AgentLoop fast-path dispatch

`AgentLoop.run()` keeps slash handling before typing indicators and before any LLM call.

- Slash input first runs authorization checks.
- Authorized static commands (`/help`, `/new`, `/status`) are resolved directly.
- Authorized tool-backed commands (`/history`, `/remember`) dispatch via helpers.

This preserves deterministic behavior and avoids adapter-level command parsing.

### 3) `/history` informational contract

`/history` is intentionally informational (YAGNI) and does not read history directly.
It returns deterministic guidance text that points the owner to explicit history recall
via normal assistant interaction and existing history tooling.

### 4) `/remember` concurrency semantics

`/remember` uses read-modify-write over global `MEMORY.md`, which is race-prone under
concurrent channel loops. To prevent silent lost updates, slash `/remember` writes are
serialized in-process with a shared async lock around:

1. load current memory text,
2. merge appended bullet line,
3. write via `memory_write`.

Guarantee: no lost updates for concurrent slash `/remember` commands in one process.
Non-slash `memory_write` calls (LLM/tooling/cron/heartbeat) keep existing behavior and
are out of scope for this command-pack guarantee.

## Rollout Preconditions

- CLI channel is always authorized for slash commands.
- Matrix and Email slash use require configured owner aliases for those channels.
- Without matching owner alias attribution, slash commands are denied by policy.

## `/status` Response Contract

`/status` returns a fixed, testable text schema:

- `Current session status:`
- `- channel: <channel>`
- `- physical_session: <session-id>`
- `- logical_session: <session-id or session-id#gN>`
- `- next_turn_history_backfill: <true|false>`

Field names are stable and must not vary across channels.

## Components

- `squidbot/core/slash_commands.py`
  - Parse `/command args` safely.
  - Normalize command names (`lower()`).
  - Return structured action requests for runtime execution.
- `squidbot/core/agent.py`
  - Add command dispatch helpers (`_handle_status_command`,
    `_handle_history_command`, `_handle_remember_command`).
  - Enforce owner-only access for all slash commands.
  - Serialize `/remember` writes with shared lock.
  - Execute command actions before typing/LLM flow.
- `tests/core/test_agent.py`
  - Add coverage for bypass, authorization, and error paths.
- `tests/core/test_slash_commands.py`
  - Validate parser behavior for args, empty args, and unknown commands.
- `tests/adapters/test_channel_loops.py`
  - Add parity test showing slash behavior is channel-agnostic through gateway loops.

## Data Flow

1. User sends message in any channel.
2. `AgentLoop` detects string input and calls slash router.
3. If router returns `handled=True`:
   - Resolve authoritative actor sender from channel-specific sources.
   - Run owner check and deny if unauthorized.
   - `/status`: build fixed-schema response from in-memory session state and send.
   - `/history`: send informational history guidance text.
   - `/remember <text>`: validate text, run serialized memory-write workflow, send.
   - Return immediately.
4. If not handled, continue normal typing -> LLM -> tools pipeline.

## Error Handling

- Unknown command: deterministic error with `/help` hint.
- Missing argument for `/remember`: usage guidance.
- Unauthorized sender on non-CLI slash commands: deterministic access-denied response.
- Matrix slash request without `matrix_sender_id`: deterministic access-denied response.
- Missing required tool registration: deterministic unavailable response.
- Tool runtime exception or `ToolResult(is_error=True)`: concise user-visible error text,
  no fallback LLM interpretation.

## Testing Approach

- Parser tests:
  - `/status`, `/history foo`, `/remember bar` parse correctly.
  - `/history` and `/remember` without args return validation errors.
  - Unknown command behavior remains unchanged.
- Core agent tests:
  - `/status`, `/history`, `/remember` bypass LLM calls.
  - Owner-only policy enforced for `/help`, `/new`, `/status`, `/history`, and `/remember`.
  - Matrix owner auth uses `matrix_sender_id` provenance only.
  - Missing Matrix sender attribution is denied deterministically.
  - `/status` exact field contract is asserted.
  - Failure paths cover missing tool, tool exception, and `ToolResult(is_error=True)`.
  - Concurrency test verifies no lost notes for concurrent slash `/remember` commands.
- Gateway/channel parity:
  - At least one channel-loop level test proves slash behavior remains identical across
    channel adapters because command handling stays in `AgentLoop`.

## Success Criteria

- Three new commands work consistently across CLI, Matrix, and Email.
- No LLM request occurs for slash command execution.
- Owner-only guard is enforced for all slash commands.
- `/history` slash response stays informational-only (no direct history retrieval).
- Matrix slash authorization is based on `matrix_sender_id` provenance.
- Missing Matrix sender attribution denies slash deterministically.
- `/remember` avoids lost updates for concurrent slash `/remember` calls.
- Existing `/help` and `/new` behavior remains stable.
- Full test suite passes with strict lint/type gates.
