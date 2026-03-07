# Dashboard Config Activation — Design Document

**Date:** 2026-03-05
**Status:** Proposed

## Motivation

Today dashboard startup is split between two CLI commands:

- `squidbot gateway` starts channels without the dashboard API.
- `squidbot dashboard` starts the same gateway with dashboard API enabled.

This is redundant operationally because dashboard availability is a runtime capability, not a separate mode. We want one startup command (`squidbot gateway`) and one configuration switch to decide whether the API is enabled.

## Goal

Enable dashboard API activation via config (`dashboard.enabled`) so operators can run a single entrypoint (`squidbot gateway`) and remove `squidbot dashboard`.

## Scope

### In scope

- Add `dashboard.enabled` to settings schema.
- Make gateway runtime decision purely config-driven.
- Remove `squidbot dashboard` CLI command.
- Update tests and README for the new behavior.

### Out of scope

- Changes to dashboard HTTP endpoints.
- Changes to frontend dashboard behavior.
- New migration CLI alias or compatibility shim.

## Current State

- `squidbot/cli/main.py` defines both `gateway` and `dashboard` commands.
- `squidbot/cli/gateway.py::_run_gateway` accepts `dashboard_enabled: bool = False`.
- `squidbot/config/schema.py::DashboardConfig` has `host` and `port`, but no `enabled` flag.
- Tests assert `main.dashboard(...)->_run_gateway(..., dashboard_enabled=True)` wiring.

## Proposed Design

### Configuration

Extend `DashboardConfig` with:

- `enabled: bool = False`

Result:

- Dashboard API startup policy lives in config.
- Localhost bind validation remains unchanged (`host` loopback-only).

### Runtime activation

Gateway decides dashboard startup from settings:

- If `settings.dashboard.enabled` is `True`: initialize dashboard runtime and run dashboard server task.
- If `False`: skip dashboard runtime and server task.

The runtime no longer depends on a `dashboard_enabled` function argument.

### CLI surface

Keep only:

- `squidbot gateway` (single process entrypoint)

Remove:

- `squidbot dashboard`

This is an intentional breaking CLI change accepted by the requester.

## Data Flow

1. User sets `dashboard.enabled` in config.
2. User runs `squidbot gateway`.
3. `_run_gateway()` loads settings.
4. Gateway conditionally starts dashboard runtime/server based on `settings.dashboard.enabled`.

## Error Handling

- Existing loopback host validation remains authoritative.
- Missing `dashboard` block still receives defaults via Pydantic.
- Dashboard disabled path remains a no-op (no extra warnings).

## Testing Strategy

### Schema tests

- Assert `dashboard.enabled` exists and defaults to `False`.
- Keep existing loopback host validation coverage.

### Gateway integration tests

- Assert dashboard server starts when `settings.dashboard.enabled=True`.
- Assert it does not start when `False`.

### CLI tests

- Remove command-specific tests for `dashboard` command.
- Ensure `gateway` command still wires logging and `_run_gateway(config_path=...)`.

## Documentation Updates

- Remove `squidbot dashboard` from CLI command list.
- Document config-driven activation:

```json
{
  "dashboard": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 8765
  }
}
```

- Mention migration path: use `squidbot gateway` after enabling config flag.

## Risks and Mitigations

- **Risk:** Existing users call `squidbot dashboard` and hit unknown command.
  - **Mitigation:** Explicit README migration note.
- **Risk:** Tests using `SimpleNamespace` settings miss new field.
  - **Mitigation:** Update test helpers to include `dashboard.enabled` defaults.

## Acceptance Criteria

- `dashboard.enabled` exists in config schema and defaults to `False`.
- `squidbot dashboard` command no longer exists.
- `squidbot gateway` conditionally starts dashboard API from config only.
- Full lint/type/test suite passes.
