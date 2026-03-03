# Room-Scoped Session Model for Matrix — Design

## Problem

Matrix inbound messages currently create sessions keyed by sender (`matrix:@alice:...`).
In group rooms this makes the agent behave like parallel 1:1 threads instead of one
room-level participant.

## Goal

Switch Matrix session identity from sender-scoped to room-scoped so the agent treats
one Matrix room as one shared conversation context.

## Non-Goals

- No slash-command implementation in this change set.
- No changes to Email or CLI session identity.
- No room-wide reset command behavior yet.

## Architecture

### Session identity

- For Matrix text/media/reaction events, use `Session(channel="matrix", sender_id=room_id)`.
- Keep real Matrix sender attribution in metadata (`matrix_sender_id`) so we can preserve
  owner checks, logging attribution, and memory labels.

### Persistence attribution

- `AgentLoop.run()` gets a new optional `user_sender_id` parameter.
- If provided, `persist_exchange()` stores that sender ID instead of `session.sender_id`.
- Gateway channel loops pass `user_sender_id` from inbound metadata when available.

### MessageTool authorization compatibility

- `MessageTool` currently authorizes routed sends based on `current_session.sender_id`.
- With room-scoped sessions, this becomes room ID and would break owner detection.
- Add optional `current_sender_id` to `MessageTool` and use it for owner checks.
- Default remains `current_session.sender_id` for non-Matrix channels.

## Data Flow

1. Matrix event arrives with `event.sender` and `room_id`.
2. Adapter emits `InboundMessage` with:
   - `session = Session(channel="matrix", sender_id=room_id)`
   - `metadata["matrix_sender_id"] = event.sender`
3. Gateway calls `AgentLoop.run(..., user_sender_id=metadata["matrix_sender_id"])`.
4. Memory persists user message with human sender ID while session identity stays room-scoped.

## Error Handling

- If `matrix_sender_id` is missing, fallback to `session.sender_id` (room ID) to avoid drops.
- Existing adapter/tool error handling remains unchanged.

## Testing Strategy

- Update Matrix adapter tests to assert room-scoped `session.sender_id` and metadata sender field.
- Add AgentLoop test to verify `user_sender_id` is persisted.
- Add gateway helper tests for forwarding `user_sender_id` to `AgentLoop.run()`.
- Add MessageTool tests to ensure owner routing uses `current_sender_id`.
