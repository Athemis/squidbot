# Design: Matrix DM E2EE Support

## Date

2026-02-28

## Status

Approved

## Goal

Enable reliable handling of end-to-end encrypted Matrix direct messages so inbound DM text reaches
`AgentLoop` and receives replies in the existing Matrix channel flow.

Also allow automatic room join on invitation events when the invitation sender is a configured
owner identity (applies to owner-invited DMs and owner-invited group rooms).

## Context

Current logs confirm the Matrix adapter connects, syncs, and is joined to rooms, but encrypted DM
messages do not reach `_handle_text()`. The current adapter only wires callbacks for
`RoomMessageText`, `RoomMessageMedia`, and a generic reaction handler.

The project already stores state under `~/.squidbot/` and the selected requirement is to persist
Matrix crypto state at `~/.squidbot/crypto`.

## Approaches Considered

### A. Full matrix-nio E2EE client setup with persistent store (selected)

Create `AsyncClient` with encryption enabled and a persistent per-user store path. Keep existing
event handlers, but add encrypted-event observability and fail-fast logs when E2EE dependencies are
missing.

Pros:
- Solves the DM problem at the root
- Survives restarts via persisted crypto state
- Minimal architectural change (adapter-only)

Cons:
- Depends on e2ee runtime support (`matrix-nio[e2e]` / libolm)

### B. Ephemeral/session-only crypto state

Enable encryption without a durable store.

Pros:
- Less IO complexity

Cons:
- Unreliable across restarts
- Regressions likely when keys/sessions rotate

### C. Logging-only for encrypted events

Detect and report encrypted events but do not decrypt.

Pros:
- Very small change

Cons:
- Does not make encrypted DMs usable

## Selected Design

Implement Approach A.

### Architecture

- Keep the current `MatrixChannel` public interface unchanged.
- Configure `nio.AsyncClient` with encryption enabled and persistent store sync tokens.
- Use per-user crypto store path:
  - base: `~/.squidbot/crypto`
  - channel namespace: `matrix`
  - user leaf: sanitized `user_id`
- Perform an initial sync before `sync_forever()` and log E2EE readiness state.
- Add explicit observability for encrypted inbound events and decryption failures.
- Register an invite handler that auto-joins invited rooms only if the inviter is in the owner
  allowlist derived from `settings.owner.aliases` for Matrix.
- Derive owner Matrix IDs in gateway wiring and pass them into `MatrixChannel`.

### Data Flow

1. `receive()` calls `_connect()`.
2. `_connect()` creates an E2EE-enabled `AsyncClient` bound to persistent store path.
3. `_sync_loop()` runs initial sync, logs room membership + encryption readiness.
4. Incoming encrypted DM is decrypted by nio client path and delivered through normal
   message callbacks.
5. Accepted inbound messages are queued and processed by gateway loop and `AgentLoop` as today.
6. Invitation membership events are evaluated:
   - inviter in owner allowlist -> `join(room_id)` and log success/failure
   - inviter not allowlisted -> log and ignore invitation

### Error Handling

- If E2EE dependencies are unavailable at startup, emit a clear warning with remediation text and
  keep channel alive for unencrypted rooms.
- If encrypted events arrive but are not decryptable, log event type, room, sender, and reason.
- If E2EE is unavailable and an encrypted room/event is encountered, emit an error-level log for
  that room/event while continuing gateway operation.
- If invite auto-join is attempted and join fails, log room id, inviter, and server error.
- If invite sender is unknown or not owner, log drop reason and do not join.
- Keep existing non-fatal adapter behavior (log errors, do not crash gateway loop).

### E2EE Capability Detection

- `MatrixChannel` keeps an explicit runtime flag (for example `self._e2ee_available: bool`) that is
  set during `_connect()` based on deterministic capability probing.
- Probe criteria:
  - `nio.AsyncClientConfig(encryption_enabled=True, store_sync_tokens=True)` can be constructed.
  - E2EE-enabled `nio.AsyncClient(..., config=..., store_path=...)` can be created.
- If probing fails, set `self._e2ee_available = False`, continue in degraded mode, and emit startup
  warning logs with a concise reason (no secrets).
- Encrypted-event handling must branch on this flag and emit error-level logs when encrypted events
  are seen while degraded.

### Security and Persistence

- Crypto store lives under `~/.squidbot/crypto/matrix/<sanitized-user-id>`.
- Crypto-store directories are created with owner-only permissions (`0700`).
- If permission hardening fails, emit a warning and continue degraded for encrypted traffic in that
  runtime (no crash), with explicit startup reason logging.
- Do not log secrets, access tokens, or key material.
- Logs may include room ID, sender ID, and event IDs for debugging.

## Testing Strategy (TDD)

1. Add failing adapter and wiring tests for:
   - E2EE client config/store path initialization
   - encrypted inbound event reaches normal queue path after decryption
   - encrypted-event observability logs
   - graceful startup when E2EE support is unavailable
   - error logging when encrypted events arrive while E2EE is unavailable
   - owner-only invite auto-join behavior for DM and group invites
   - gateway owner-alias extraction and MatrixChannel wiring
2. Run tests to confirm failures.
3. Implement minimal code to satisfy each test.
4. Run focused Matrix adapter tests, then full repository checks.

## Scope

In scope:
- `MatrixChannel` E2EE setup and startup diagnostics
- Persistent crypto-store path derivation under `~/.squidbot/crypto`
- Encrypted-event logging for investigation
- Owner-only invitation auto-join handling (owner-invited DMs and groups)
- Gateway wiring for owner alias propagation to Matrix channel
- Adapter and gateway tests for above behavior

Out of scope:
- Interactive device verification UX
- Cross-channel architecture changes outside Matrix adapter/config

## Acceptance Criteria

| ID | Requirement |
|---|---|
| AC1 | With E2EE available, encrypted inbound DM text is processed through the normal inbound queue and reaches `AgentLoop`. |
| AC2 | Owner-invited room invites (DM or group) trigger auto-join; non-owner invites are ignored and logged. |
| AC3 | When E2EE dependencies are missing, startup degrades with warning logs; unencrypted rooms still function. |
| AC4 | When encrypted events are seen while E2EE is unavailable, error logs include room/event context without secrets. |
| AC5 | Startup logs include E2EE readiness mode (`enabled` or `degraded`), degraded reason when present, and current joined-room count. |

Traceability note for AC1:
- AC1 is considered complete only when evidence exists at the gateway boundary (`AgentLoop.run(...)`
  invocation), not just adapter queue insertion.

Operational note:
- Degraded mode is an accepted fallback state, but deployments that are expected to process
  encrypted DMs must reach readiness mode `enabled` for full AC1 fulfillment.

## Validation Commands

- `uv run ruff check .`
- `uv run ruff format . --check`
- `uv run pytest`
- `uv run mypy squidbot/`
