# GatewayState & StatusPort — Design Document

**Date:** 2026-02-22
**Status:** Approved

## Motivation

The design document (`2026-02-21-squidbot-design.md`) specifies `SessionInfo`,
`ChannelStatus`, `GatewayState`, and a complete `StatusPort`. None of these are
implemented yet. They form the foundation for the future dashboard and give the gateway
a well-typed runtime state object.

## Scope

- Add `SessionInfo` + `ChannelStatus` dataclasses to `core/models.py`
- Complete `StatusPort` in `core/ports.py` (correct return types + `get_skills()`)
- Add `GatewayState` dataclass and `GatewayStatusAdapter` in `cli/main.py`
- Wire the gateway to populate `GatewayState` during runtime (active sessions, channel status)
- No dashboard UI — only the data layer

Out of scope: `ChannelStatus.connected` health-checking (always `True` while loop runs),
remote dashboard, `squidbot status` refactoring (it reads `Settings` directly, not via port).

## New Dataclasses in `core/models.py`

```python
@dataclass
class SessionInfo:
    """Runtime metadata for an active conversation session."""
    session_id: str       # "matrix:@user:matrix.org"
    channel: str          # "matrix", "email", "cli"
    sender_id: str        # "user@example.com"
    started_at: datetime  # time of first message in this gateway run
    message_count: int    # messages handled since gateway start

@dataclass
class ChannelStatus:
    """Runtime status of a channel adapter."""
    name: str             # "matrix", "email"
    enabled: bool
    connected: bool       # True while channel loop is running
    error: str | None = None
```

## Updated `StatusPort` in `core/ports.py`

```python
class StatusPort(Protocol):
    def get_active_sessions(self) -> list[SessionInfo]: ...
    def get_channel_status(self) -> list[ChannelStatus]: ...
    def get_cron_jobs(self) -> list[CronJob]: ...
    def get_skills(self) -> list[SkillMetadata]: ...  # added
```

`get_skills()` delegates to the `SkillsPort` already wired in the gateway.

## `GatewayState` and `GatewayStatusAdapter` in `cli/main.py`

`GatewayState` is **not** a core concept — it belongs in the CLI/gateway layer:

```python
@dataclass
class GatewayState:
    active_sessions: dict[str, SessionInfo]  # session_id → SessionInfo
    channel_status: list[ChannelStatus]      # one entry per enabled channel
    started_at: datetime
```

`GatewayStatusAdapter` is a thin wrapper implementing `StatusPort` by reading from
`GatewayState`, delegating `get_cron_jobs()` to `MemoryPort`, and `get_skills()` to
`SkillsPort`:

```python
class GatewayStatusAdapter:
    def __init__(
        self,
        state: GatewayState,
        storage: MemoryPort,
        skills_loader: SkillsPort,
    ) -> None: ...

    def get_active_sessions(self) -> list[SessionInfo]:
        return list(self._state.active_sessions.values())

    def get_channel_status(self) -> list[ChannelStatus]:
        return list(self._state.channel_status)

    def get_cron_jobs(self) -> list[CronJob]:
        # synchronous read from in-memory cache kept by CronScheduler
        return self._state.cron_jobs_cache

    def get_skills(self) -> list[SkillMetadata]:
        return self._skills_loader.list_skills()
```

For `get_cron_jobs()` the simplest approach: `GatewayState` holds a `cron_jobs_cache:
list[CronJob]` updated by `CronScheduler` after each load/save. No async needed because
the scheduler already holds the current list in memory.

## Gateway Integration

After building channels in `_run_gateway()`:

1. `GatewayState` is instantiated with `started_at=datetime.now()` and an empty
   `active_sessions` dict.
2. Channel status entries are appended for each enabled channel immediately after the
   channel object is created.
3. `_channel_loop()` is extended to update `state.active_sessions` on each inbound
   message: first message creates a `SessionInfo`, subsequent messages increment
   `message_count`.
4. `CronScheduler` is updated to keep `state.cron_jobs_cache` current.

## `cron_jobs_cache` Update Strategy

`CronScheduler` already holds jobs in memory. Rather than coupling the scheduler to
`GatewayState`, the simplest approach is to store the cache directly on `GatewayState`
and update it from the gateway's `on_cron_due` callback and from the initial load:

```python
state.cron_jobs_cache = cron_jobs  # after initial load
# after any save:
state.cron_jobs_cache = updated_jobs
```

## File Changes

| File | Change |
|------|--------|
| `squidbot/core/models.py` | Add `SessionInfo`, `ChannelStatus` |
| `squidbot/core/ports.py` | Update `StatusPort`: typed return values + `get_skills()` |
| `squidbot/cli/main.py` | Add `GatewayState`, `GatewayStatusAdapter`; wire into gateway |
| `tests/core/test_models.py` | Tests for new dataclasses |
| `tests/adapters/test_gateway_status.py` | Tests for `GatewayStatusAdapter` |
