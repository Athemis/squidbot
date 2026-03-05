# Dashboard Web Interface — Design Document

**Date:** 2026-03-05
**Status:** Approved

## Motivation

The original architecture reserved `squidbot/adapters/dashboard/` for a future dashboard,
but only the gateway status data layer exists today (`GatewayState`, `GatewayStatusAdapter`).
Operators currently rely on terminal output and the CLI for diagnostics and configuration.

We need a local web interface for setup and incident handling that stays lightweight,
maintains clear data/API boundaries, and supports future expansion.

## Product Scope

### In scope (v1)

- Localhost-only web UI (no remote exposure)
- Multi-page operator interface:
  - Overview / monitoring
  - Logs (live tail)
  - Config (targeted editable settings)
  - Operator chat (minimal fallback channel)
- FastAPI backend with JSON APIs
- Svelte 5 + TypeScript + Vite frontend
- Adaptive polling for status/logs:
  - active tab: 2s
  - background tab: 15s
- Chat transport without polling (streaming response)
- Logs default window: newest 200 lines + dynamic "load older"
- Config apply flow: save first, optional explicit restart step

### Out of scope (v1)

- Authentication/authorization (localhost-only by design)
- Full config editing UI for every nested field
- Channel start/stop/reconnect controls from web UI
- Multi-user chat semantics
- SSE/WebSocket for status/logs (candidate for v2)

## Architecture

The dashboard runs in-process with the gateway so it can access live runtime state safely
without introducing another daemon or IPC protocol.

1. `squidbot gateway` remains unchanged for current workflows.
2. New `squidbot dashboard` command starts:
   - gateway loops (matrix/email/scheduler/heartbeat)
   - local FastAPI server
3. FastAPI endpoints read from shared runtime objects:
   - `GatewayState` for sessions/channels/cron snapshot
   - in-memory log ring buffer for tail views
   - `Settings` load/save service for targeted config edits
   - chat bridge that streams `AgentLoop` output chunks as NDJSON/SSE-style lines

This keeps one source of truth for runtime data and avoids duplicate APIs.

## Dependency and Build Contract

- Backend runtime dependencies are explicit in `pyproject.toml`:
  - `fastapi`
  - `uvicorn`
- CI includes a dashboard app-factory import/build check so missing dependencies fail early.
- Frontend build dependencies stay inside `web/dashboard` and are locked via lockfile.

## Local Security Baseline (v1)

v1 intentionally has no login, but mutating endpoints still need local write safety.

- Dashboard server default bind is `127.0.0.1`; any configured host value is validated
  as loopback-only (`127.0.0.1` or `localhost`).
- Mutating routes (`PATCH /api/config`, `POST /api/config/restart-intent`, `POST /api/chat/stream`)
  enforce:
  - `Host` is loopback (`127.0.0.1` or `localhost`).
  - `Origin` is loopback when present.
  - `X-Squidbot-Local-Nonce` matches a runtime nonce provided by `GET /api/bootstrap`.
- No cross-origin writes in v1.

This keeps the no-auth model while preventing accidental browser-driven writes from unrelated pages.

## Components

### Backend

- `squidbot/adapters/dashboard/runtime.py`
  - Dashboard runtime dataclasses and coordination objects.
  - Holds references to gateway state, log buffer, config path, and chat dependencies.

- `squidbot/adapters/dashboard/logs.py`
  - Ring-buffer implementation for structured log entries.
  - Supports cursor/offset pagination for "load older".

- `squidbot/adapters/dashboard/chat.py`
  - Minimal streaming channel adapter for `AgentLoop.run()`.
  - Converts emitted chunks into an async stream consumable by FastAPI response streaming.

- `squidbot/adapters/dashboard/api.py`
  - FastAPI app factory and route handlers.
  - Routes include:
    - `GET /api/bootstrap`
    - `GET /api/overview`
    - `GET /api/logs?before=<cursor>&limit=<n>`
    - `GET /api/config`
    - `PATCH /api/config`
    - `POST /api/config/restart-intent` (ack-only; no auto-restart)
    - `POST /api/chat/stream`

- `squidbot/cli/gateway.py`
  - Extended logging setup to mirror logs into dashboard buffer when enabled.
  - Hook dashboard runtime into `_run_gateway()` lifecycle.

- `squidbot/cli/main.py`
  - New `dashboard` command entrypoint.

### Frontend

- `web/dashboard/` (new frontend workspace)
  - `Svelte + TS + Vite` app.
  - Routes/pages:
    - `/overview`
    - `/logs`
    - `/config`
    - `/chat`
  - Shared API client and stores.
  - Adaptive polling utility tied to `document.visibilityState`.

### Integration boundary

- Backend serves frontend assets from package-owned static files under
  `squidbot/adapters/dashboard/static/`.
- Frontend build output is copied into that package path before release/install.
- API remains JSON-first; frontend render and backend business logic stay decoupled.

## Distribution and Packaging

The dashboard must work when squidbot is installed as a tool, not only when run from a git checkout.

- `web/dashboard` remains the source frontend project.
- Release build step copies `web/dashboard/dist/*` to
  `squidbot/adapters/dashboard/static/`.
- `pyproject.toml` build config includes `squidbot/adapters/dashboard/static/**` in package data.
- FastAPI serves only package-owned assets at runtime.
- Packaging is enforced by automation (build helper invoked in CI packaging job), not manual-only.
- CI validates: build artifact -> install artifact -> `GET /` serves packaged dashboard HTML.

## CI Ownership and Merge Gate

- Source of truth: `.github/workflows/ci.yml` dashboard job(s).
- Accountable owner: repository maintainers (GitHub role: Maintain).
- Canonical mapping artifact: `docs/ci/dashboard-checks.md`.
- Mandatory CI gates for dashboard-related changes:
  - frontend tests and production build
  - asset copy into package path
  - wheel/sdist build
  - clean-environment install from built artifact
  - dashboard root smoke check (`GET /` serves packaged HTML)
- Required check names (branch protection):
  - `dashboard-frontend`
  - `dashboard-package-smoke`
- Update trigger: whenever a dashboard CI job name changes, update
  `docs/ci/dashboard-checks.md` in the same PR.
- Merge policy: dashboard PRs are not mergeable unless all required dashboard checks pass.

## Data Flow

### Overview

1. Frontend calls `GET /api/overview` every 2s (active) or 15s (background).
2. Backend reads `GatewayState` snapshot and returns:
   - channel status list
   - active session summary
   - cron summary
   - uptime

### Logs

1. Initial request: `GET /api/logs?limit=200`.
2. Backend returns newest logs plus `next_before_cursor`.
3. "Load older" calls `GET /api/logs?before=<cursor>&limit=200`.
4. Polling appends new entries while preserving scroll position policy.

### Config

1. `GET /api/config` returns a restricted editable projection (not full raw file).
2. `PATCH /api/config` validates payload, merges into `Settings`, writes config JSON.
3. Backend marks `restart_required=true` when changes affect running adapters.
4. `POST /api/config/restart-intent` records explicit operator intent.
5. UI shows explicit "Restart gateway" guidance; no automatic process restart in v1.

### Operator chat

1. UI submits prompt to `POST /api/chat/stream`.
2. Handler creates dashboard session (`channel="dashboard", sender_id="local"`).
3. Agent output chunks are streamed back immediately.
4. Request ends when agent turn completes.

## Error Handling

- API input errors return `400` with deterministic messages.
- Unexpected backend failures return `500` with stable error payload shape.
- Polling endpoints include `last_success_at` hints for degraded-mode banners.
- Chat stream sends terminal error frame then closes cleanly.
- Log buffer overflow is bounded and intentional (oldest entries dropped first).

## Testing Strategy

### Unit tests

- Log buffer paging and cursor behavior
- Config projection and patch validation
- Chat streaming adapter chunk ordering and completion semantics

### API tests

- `GET /api/overview` shape and field invariants
- `GET /api/logs` pagination contract
- `PATCH /api/config` safe-field enforcement
- `POST /api/config/restart-intent` intent acknowledgement contract
- `POST /api/chat/stream` emits incremental chunks and closes
- mutating route rejects invalid host/origin/nonce

### CLI/integration tests

- `squidbot dashboard` command wires gateway + API startup
- Existing `squidbot gateway` behavior remains unchanged
- gateway dashboard startup/shutdown is testable with controlled cancellation

### Frontend tests (lightweight)

- Store tests for adaptive polling mode transitions
- View tests for logs "load older" and restart-required config banners
- bootstrap nonce is attached to mutating requests

### Packaging tests

- package-owned static assets are present in installed environment
- root dashboard route serves packaged `index.html`

## Risks and Mitigations

- **Risk:** In-process dashboard can impact gateway if buggy.
  - **Mitigation:** Keep API handlers thin; isolate mutable state behind runtime service.
- **Risk:** Streaming chat handler leaks tasks on client disconnect.
  - **Mitigation:** cancellation-aware producer task and `finally` cleanup path.
- **Risk:** localhost no-auth mutating routes allow unsafe local browser writes.
  - **Mitigation:** loopback host/origin enforcement plus local nonce requirement.
- **Risk:** dashboard works in repo but not from installed CLI package.
  - **Mitigation:** package-owned static assets and packaging verification tests.
- **Risk:** Frontend/tooling drift introduces CI friction.
  - **Mitigation:** separate frontend commands, deterministic lockfile, explicit docs.

## Requirement Traceability

| Requirement | API/UI Location | Tests |
|-------------|------------------|-------|
| Monitoring overview | `GET /api/overview`, `/overview` | API overview tests + polling store tests |
| Raw logs + load older | `GET /api/logs`, `/logs` | log buffer unit tests + logs pagination API tests |
| Targeted config edit | `GET/PATCH /api/config`, `/config` | config projection/validation tests |
| Optional restart action | `POST /api/config/restart-intent`, `/config` banner/action | restart-intent API tests + config view tests |
| Operator chat without polling | `POST /api/chat/stream`, `/chat` | chat streaming tests + disconnect cleanup tests |
| Local write safety | mutating endpoints with loopback+nonce checks | security negative tests |
| Installed package static assets | packaged static serving at `/` | packaging/static asset tests |
| CI merge gate enforcement | `.github/workflows/ci.yml` required checks | branch protection check mapping review |

## File Plan (high-level)

| File | Change |
|------|--------|
| `squidbot/cli/main.py` | Add `dashboard` command |
| `squidbot/cli/gateway.py` | Add dashboard runtime hooks + log mirroring |
| `squidbot/adapters/dashboard/runtime.py` | New runtime coordination types |
| `squidbot/adapters/dashboard/logs.py` | New log ring buffer |
| `squidbot/adapters/dashboard/chat.py` | New streaming chat bridge |
| `squidbot/adapters/dashboard/api.py` | New FastAPI app + JSON routes |
| `web/dashboard/*` | New Svelte + TS + Vite frontend |
| `tests/adapters/test_dashboard_*.py` | New backend dashboard tests |
| `tests/cli/test_main_dashboard.py` | New CLI command tests |
