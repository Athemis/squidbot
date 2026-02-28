# Design: Scheduler Interval Validation (`every N`)

## Problem

`parse_schedule()` currently treats any integer in `every N` as valid, including `0` and negative values.
That allows invalid schedules like `every 0` or `every -1` to pass validation and then evaluate as due on every scheduler tick.

## Root Cause

In `squidbot/core/scheduler.py`, the interval branch only checks parseability:

```python
if schedule.startswith("every "):
    try:
        int(schedule.split()[1])
        return now.replace(microsecond=0)
    except IndexError, ValueError:
        return None
```

There is no positivity check for the parsed seconds value.

## Design Decision

Add a positivity guard in `parse_schedule()`:

- Parse seconds into a named variable.
- Return `None` when `seconds <= 0`.
- Keep all other behavior unchanged.

This preserves existing architecture:

- `parse_schedule()` decides whether a schedule is valid.
- `validate_job()` relies on `parse_schedule() is None` for invalid schedules.
- `add_job()` and `CronAddTool` already propagate validation errors correctly.

## Why This Scope

- Minimal change with maximal impact.
- No API surface changes.
- No config changes.
- No migration needed.

## Tests to Add

- `parse_schedule(..., schedule="every 0") -> None`
- `parse_schedule(..., schedule="every -1") -> None`
- `parse_schedule(..., schedule="every 1") -> datetime`
- `validate_job(..., schedule="every 0") -> error string`
- `validate_job(..., schedule="every -1") -> error string`

## Non-Goals

- No retry policy changes in scheduler delivery.
- No fetch_url SSRF redesign.
