# Design: One-Time Cron Job Support

**Date:** 2026-03-02  
**Status:** Approved

## Problem

The agent claims it cannot schedule a one-time task. The cron infrastructure
(`CronJob`, `CronScheduler`, `CronAddTool`) supports only recurring schedules
(cron expressions and `every N` intervals). There is no way to create a job that
fires exactly once and is then removed.

## Decision

Add `once: bool = False` to `CronJob`. When `once=True`, the scheduler deletes
the job after it fires instead of updating `last_run`. The cron expression
(parsed by cronsim) determines *when* the job fires — `once` only controls
*what happens after*.

## Alternatives Considered

**A — ISO datetime in `schedule` field:** Accept `"2026-03-03T15:00:00"` as a
schedule string. No model change needed; one-time semantics are implicit from the
string format. Rejected because it bypasses cronsim entirely and conflates the
schedule-format with the recurrence-intent.

**C — `run_at: datetime | None` field:** Cleanest semantic separation, but
requires non-trivial model and serialization changes, and leaves `schedule`
empty for one-time jobs.

Approach B (`once: bool`) was chosen because it:
- Keeps cronsim as the sole schedule parser
- Requires minimal model change (backward-compatible default)
- Has clear, explicit semantics: `once=True` means "fire once, then delete"

## Architecture

### `CronJob` model (`squidbot/core/models.py`)

Add one field:

```python
once: bool = False
```

Default `False` ensures existing `jobs.json` entries remain valid without
migration. JSON serialization is automatic (bool → true/false).

**Constraint:** `once=True` with an interval schedule (`"every N"`) is
semantically contradictory and is rejected at validation time.

### `CronScheduler._tick()` (`squidbot/core/scheduler.py`)

Current behaviour: for every due job, set `last_run = now`, then save.

New behaviour:

```
for each due job:
    invoke on_due(job)
    if job.once:
        drop from the saved list  ← deleted
    else:
        update last_run, keep in list
save the resulting list
```

`parse_schedule()` and `is_due()` are **unchanged** — cronsim still drives
all timing decisions.

### `cron_ops.py` (`squidbot/core/cron_ops.py`)

`validate_job()`: reject `once=True` + `"every N"` schedule with a clear
error message.

`format_jobs()`: append `[once]` to the name line for one-time jobs:

```
  [on] abc12345  Termin-Erinnerung  [once]
       schedule: 30 15 3 3 *  timezone: Europe/Berlin  channel: matrix:@user:…
       message:  Nicht vergessen: Zahnarzt
```

`set_enabled()`: propagate `once` when rebuilding the dataclass (copy field).

### `CronAddTool` (`squidbot/adapters/tools/cron.py`)

Add optional `once` parameter to the JSON schema:

```json
"once": {
  "type": "boolean",
  "description": "If true, the job runs exactly once and is deleted after firing. Use with a specific cron expression, e.g. '30 15 3 3 *' for a one-time reminder."
}
```

Pass `once` through to `CronJob` construction.

## Data Flow

```
Agent calls cron_add(schedule="30 15 3 3 *", once=True, timezone="Europe/Berlin")
  → CronAddTool.execute() validates, builds CronJob(once=True)
  → saved to jobs.json

[scheduler tick, 15:30 on March 3rd]
  → is_due() → True  (cronsim finds match)
  → on_due(job) called  ← message delivered
  → job.once is True  → job NOT appended to kept list
  → save_cron_jobs(kept)  ← job gone from storage
```

## Error Handling

- `once=True` + `"every N"` → validation error returned from `CronAddTool`,
  job is never persisted.
- If `on_due()` raises, the exception is suppressed (existing behaviour). The
  job is still deleted (fire-and-forget semantics; no retry).

## Testing

**`tests/core/test_scheduler.py`** (new cases):
- `_tick()` with `once=True` job: after firing, job is absent from saved list.
- `_tick()` with `once=False` job: after firing, job is present with updated
  `last_run`.
- `_tick()` with mixed list: only the fired once-job is removed.

**`tests/core/test_cron_ops.py`** (new cases):
- `validate_job()` rejects `once=True` + `"every 3600"`.
- `validate_job()` accepts `once=True` + valid cron expression.
- `format_jobs()` shows `[once]` label for once-jobs, not for recurring jobs.

**`tests/adapters/tools/test_cron_tools.py`** (new cases):
- `CronAddTool` with `once=True` creates job with `once=True`.
- `CronAddTool` with `once=True` + `"every N"` returns an error result.
