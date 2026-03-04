# Cross-Channel Slash Command Pack v1 - Design

## Update

`/history` was removed per YAGNI. The shipped command pack includes `/help`, `/new`,
`/status`, and `/remember <text>`.

## Problem

The existing slash surface is too small for deterministic session control and quick memory
capture. Users should not need an LLM roundtrip for basic operational commands.

## Goal

Provide deterministic slash command handling for:

- `/help`
- `/new`
- `/status`
- `/remember <text>`

All slash commands must execute without calling the LLM.

## Authorization Policy

- CLI: slash commands are always allowed (physical host access implies owner control).
- Non-CLI channels: slash commands are owner-only.
- Matrix owner resolution uses `matrix_sender_id` from metadata.
- Missing/invalid attribution on non-CLI channels returns:
  `Access denied: slash commands are only available to the owner.`

## Command Contracts

### `/status`

Returns deterministic session diagnostics:

- `channel`
- `physical_session`
- `logical_session`
- `next_turn_history_backfill`
- `history_messages` (count of persisted messages in current logical session)

If status construction fails, return deterministic text:
`Error: unable to build session status right now.`

### `/remember <text>`

- Requires non-empty `<text>`.
- Merges note as a markdown bullet into global memory via `memory_write`.
- Uses an async lock for slash-path serialization.
- If `memory_write` is unavailable, return deterministic error.
- If tool raises, returns error text.
- If tool returns an invalid shape, return deterministic error:
  `Error: memory_write returned an invalid result.`

## Architecture

- `squidbot/core/slash_commands.py`
  - Parse command + argument.
  - Emit action metadata for `status` and `remember`.
- `squidbot/core/agent.py`
  - Authorize slash calls.
  - Dispatch command actions before typing/LLM path.
  - Build status payload and memory-write flow.
- `squidbot/core/memory.py`
  - Owner-check helper.
  - Global memory load helper.
  - Session history count helper for status.

## Testing Strategy

- Parser tests for `/status`, `/remember`, unknown commands.
- Agent tests for:
  - no-LLM slash execution,
  - CLI allow / non-CLI deny,
  - Matrix metadata sender auth,
  - `/status` contract and failure fallback,
  - `/remember` success + failure paths (missing tool, exception, error result,
    invalid result shape).

## Success Criteria

- Slash behavior is deterministic and channel-consistent.
- `/status` includes `history_messages`.
- `/remember` is robust against expected tool failure modes.
- `/history` is not part of shipped slash surface.
