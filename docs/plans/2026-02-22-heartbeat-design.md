# Heartbeat Design

**Date:** 2026-02-22
**Status:** Approved

## Overview

`HeartbeatService` adds periodic autonomous agent wake-ups to the gateway. Every N minutes
(default: 30), the agent reads `HEARTBEAT.md` from the workspace, decides if anything needs
attention, and either replies `HEARTBEAT_OK` (silent) or sends an alert to the last active
channel. Inspired by nanobot/openclaw heartbeat, scoped to minimal viable feature set.

## Architecture

```
_run_gateway()  [asyncio.TaskGroup]
    ├── MatrixChannelAdapter  ──┐
    ├── EmailChannelAdapter   ──┤→ call tracker.update(channel, session) on each inbound
    ├── CronScheduler            │
    └── HeartbeatService   ←────┘  reads tracker.channel / tracker.session
              │ every interval_minutes
              ↓
         activeHours check (zoneinfo, stdlib)
              │ inside window
              ↓
         read HEARTBEAT.md (workspace path, plain file read)
              │ not effectively empty
              ↓
         AgentLoop.run(session, prompt, last_channel)
              │
              ↓
         response contains HEARTBEAT_OK at start/end?
              ├─ yes → DEBUG log "heartbeat: ok", no channel send
              └─ no  → last_channel.send(alert text)
```

## Components

### `squidbot/core/heartbeat.py` (new)

Two classes:

**`LastChannelTracker`**
- Holds `channel: ChannelPort | None` and `session: Session | None`
- `update(channel, session)` — called by gateway on every inbound message
- Single-threaded safe (asyncio), no locking needed

**`HeartbeatService`**
- Constructor args: `agent_loop`, `tracker`, `workspace`, `config: HeartbeatConfig`
- `async def run()` — main loop: sleep → tick → repeat
- `async def _tick()` — single heartbeat execution (activeHours check, file read, agent call)
- `_is_heartbeat_empty(content: str | None) -> bool` — module-level pure function

Constants:
```python
DEFAULT_HEARTBEAT_PROMPT = (
    "Read HEARTBEAT.md if it exists in your workspace. "
    "Follow any instructions strictly. Do not repeat tasks from prior turns. "
    "If nothing needs attention, reply with just: HEARTBEAT_OK"
)
HEARTBEAT_OK_TOKEN = "HEARTBEAT_OK"
```

### `squidbot/config/schema.py` (modify)

Add `HeartbeatConfig` and extend `AgentConfig`:

```python
class HeartbeatConfig(BaseModel):
    enabled: bool = True
    interval_minutes: int = 30
    prompt: str = DEFAULT_HEARTBEAT_PROMPT   # imported constant
    active_hours_start: str = "00:00"        # HH:MM inclusive
    active_hours_end: str = "24:00"          # HH:MM exclusive; 24:00 = end of day
    timezone: str = "local"                  # IANA tz name or "local" (host tz)

class AgentConfig(BaseModel):
    ...
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
```

### `squidbot/cli/main.py` (modify)

In `_run_gateway()`:
- Instantiate `LastChannelTracker`
- Wrap channel receive loops to call `tracker.update()` on each inbound message
- Add `HeartbeatService` task to the `asyncio.TaskGroup`

## Detailed Behavior

### HEARTBEAT_OK detection

- Strip the response text
- `HEARTBEAT_OK` at **start or end** → silent drop + `logger.debug("heartbeat: ok")`
- `HEARTBEAT_OK` in the **middle** → treat as normal alert (deliver to channel)
- Entire response is only `HEARTBEAT_OK` (plus optional whitespace) → silent drop

### HEARTBEAT.md handling

| State | Behavior |
|---|---|
| File does not exist | Heartbeat runs; agent decides what to do |
| File exists, effectively empty | Skip (no API call); DEBUG log "heartbeat: skipped (empty)" |
| File exists with content | Normal heartbeat run |

"Effectively empty" = only blank lines and Markdown headings (`# ...`). Same logic as nanobot.

### activeHours

- Checked at each tick using `zoneinfo.ZoneInfo` (stdlib, Python 3.9+, no new dep)
- `timezone: "local"` → `datetime.now().astimezone()` (host timezone)
- Outside window → skip tick, DEBUG log "heartbeat: outside active hours"
- `active_hours_start == active_hours_end` → zero-width window, always skip (warn at startup)

### Session

- Heartbeat runs in `tracker.session` (last user who wrote to the gateway)
- If tracker is empty (no user has written yet) → skip tick, DEBUG log "heartbeat: no active session"

### Error handling

All exceptions in `_tick()` are caught and logged (same pattern as `CronScheduler._tick()`).
The loop continues regardless.

## Config example

```json
{
  "agents": {
    "heartbeat": {
      "enabled": true,
      "interval_minutes": 30,
      "active_hours_start": "08:00",
      "active_hours_end": "22:00",
      "timezone": "Europe/Berlin"
    }
  }
}
```

## Testing

**`tests/core/test_heartbeat.py`**
- `_is_heartbeat_empty()`: empty string, None, headings-only, checklist with content, mixed
- `HeartbeatService._tick()` with mock `AgentLoop` and `tmp_path`:
  - HEARTBEAT.md absent → agent called, response delivered
  - HEARTBEAT.md effectively empty → agent NOT called
  - Response is `HEARTBEAT_OK` → not delivered to channel
  - Response is `HEARTBEAT_OK` at start → not delivered
  - Response is alert text → delivered to `last_channel.send()`
  - tracker empty → tick skipped, agent NOT called
  - activeHours outside window → tick skipped
- No network, no real filesystem (use `tmp_path`), no `asyncio.sleep`

**`tests/core/test_last_channel_tracker.py`**
- `update()` sets channel and session
- Multiple updates → last one wins
- Initial state: both None
