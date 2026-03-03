# Cross-Channel Minimal Slash Commands — Design

## Problem

The agent currently treats all incoming text as LLM input. There is no cross-channel
control surface for operational commands such as resetting the local conversation
context.

## Goal

Add a minimal, reliable slash-command layer that works identically across CLI, Matrix,
and Email without relying on LLM interpretation.

## Scope

### In scope

- `/help`: list supported slash commands.
- `/new`: reset the active conversation context for the current session.
- Cross-channel behavior via central handling in `AgentLoop`.

### Out of scope

- Command aliases/flags (`/new room`, `/new me`, etc.).
- Channel-specific command parsing in adapters.
- New command permissions model.

## Architecture

### Core command router

- Add a new core module (`squidbot/core/slash_commands.py`) with parsing/dispatch for
  slash-prefixed text commands.
- `AgentLoop.run()` checks string user messages for slash commands before typing/LLM.
- Command replies are sent directly via `channel.send(...)` and do not call the LLM.

### Session reset model (`/new`)

- Add in-memory reset boundaries to `MemoryManager`, keyed by `session.id`.
- `MemoryManager.build_messages(...)` accepts optional `session` and filters history for
  that session to only include entries at/after the reset boundary.
- Cross-channel memory for other sessions remains available (existing behavior).

### Session attribution for robust filtering

- Introduce optional `session_id` on `Message`.
- Persisted user+assistant messages include `session_id` from `AgentLoop`.
- For legacy history entries without `session_id`, filtering falls back to
  `(channel, sender_id)` matching for compatibility.

## Data Flow

1. Inbound text arrives in any channel.
2. `AgentLoop` parses slash command.
3. If command exists:
   - `/help`: send command list and return.
   - `/new`: set reset boundary for current session, send confirmation, return.
4. Non-command input follows normal LLM/tool pipeline.
5. During normal turns, `build_messages(..., session=...)` applies reset filtering.

## Error Handling

- Unknown slash command returns concise error plus hint to `/help`.
- Empty command text (`"/"`) is treated as unknown command.
- Command handling errors return a user-visible error message, no LLM fallback.

## Testing Strategy

- Core tests for slash parser and command dispatch (`/help`, `/new`, unknown command).
- Agent tests proving slash commands bypass LLM and emit direct replies.
- Memory tests verifying reset boundaries filter history for matching session only.
- Persistence tests verifying `session_id` round-trips through JSONL serialization.
