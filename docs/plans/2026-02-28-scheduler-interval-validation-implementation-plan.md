# Scheduler Interval Validation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reject invalid interval schedules (`every 0`, `every -N`) so they cannot be created or executed as always-due cron jobs.

**Architecture:** Keep validation centralized in `parse_schedule()` and let existing validation plumbing (`validate_job` -> `add_job` -> tool/CLI error handling) enforce correctness. Extend tests at scheduler and cron-ops layers to lock in behavior.

**Tech Stack:** Python 3.14, pytest, existing cron domain modules (`scheduler.py`, `cron_ops.py`).

---

### Task 1: Add failing scheduler tests for invalid `every N`

**Files:**
- Modify: `tests/core/test_scheduler.py`
- Test: `tests/core/test_scheduler.py`

**Step 1: Write failing tests**

Add tests that assert:

```python
def test_parse_interval_zero_is_invalid():
    job = CronJob(id="1", name="test", message="hi", schedule="every 0", channel="cli:local")
    next_run = parse_schedule(job, now=datetime(2026, 2, 21, 8, 0, tzinfo=UTC))
    assert next_run is None


def test_parse_interval_negative_is_invalid():
    job = CronJob(id="1", name="test", message="hi", schedule="every -1", channel="cli:local")
    next_run = parse_schedule(job, now=datetime(2026, 2, 21, 8, 0, tzinfo=UTC))
    assert next_run is None


def test_parse_interval_one_second_is_valid():
    job = CronJob(id="1", name="test", message="hi", schedule="every 1", channel="cli:local")
    next_run = parse_schedule(job, now=datetime(2026, 2, 21, 8, 0, tzinfo=UTC))
    assert next_run is not None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_scheduler.py -q`

Expected: FAIL on zero/negative interval tests because current code returns a datetime.

**Step 3: Commit**

Do not commit yet; bundle after implementation and green tests.

### Task 2: Implement minimal validation in scheduler

**Files:**
- Modify: `squidbot/core/scheduler.py`

**Step 1: Update interval parsing logic**

In `parse_schedule()` interval branch, replace the bare parse with a guarded parse:

```python
seconds = int(schedule.split()[1])
if seconds <= 0:
    return None
return now.replace(microsecond=0)
```

Keep existing `except IndexError, ValueError` behavior unchanged.

**Step 2: Run focused scheduler tests**

Run: `uv run pytest tests/core/test_scheduler.py -q`

Expected: PASS for all scheduler tests including new interval edge cases.

### Task 3: Add failing cron-ops validation tests

**Files:**
- Modify: `tests/core/test_cron_ops.py`
- Test: `tests/core/test_cron_ops.py`

**Step 1: Write tests for invalid interval schedules at validation layer**

Add tests:

```python
def test_validate_job_returns_error_for_zero_interval() -> None:
    now = datetime(2026, 2, 27, 9, 0, tzinfo=UTC)
    error = validate_job(_job(schedule="every 0"), now=now)
    assert error is not None
    assert "Invalid schedule" in error


def test_validate_job_returns_error_for_negative_interval() -> None:
    now = datetime(2026, 2, 27, 9, 0, tzinfo=UTC)
    error = validate_job(_job(schedule="every -1"), now=now)
    assert error is not None
    assert "Invalid schedule" in error
```

**Step 2: Run focused cron-ops tests**

Run: `uv run pytest tests/core/test_cron_ops.py -q`

Expected: PASS.

### Task 4: Optional end-to-end guard via tool layer

**Files:**
- Modify: `tests/adapters/tools/test_cron_tools.py`
- Test: `tests/adapters/tools/test_cron_tools.py`

**Step 1: Add tool-level rejection test**

Add one test that creates `CronAddTool` and calls:

```python
result = await tool.execute(name="Bad", message="Ping", schedule="every 0")
assert result.is_error
assert "Invalid schedule" in result.content
```

**Step 2: Run focused tool tests**

Run: `uv run pytest tests/adapters/tools/test_cron_tools.py -q`

Expected: PASS.

### Task 5: Full verification and cleanup

**Files:**
- Verify only, no new files

**Step 1: Run targeted suite for touched areas**

Run:

`uv run pytest tests/core/test_scheduler.py tests/core/test_cron_ops.py tests/adapters/tools/test_cron_tools.py -q`

Expected: PASS.

**Step 2: Run full test suite**

Run: `uv run pytest -q`

Expected: PASS (no regressions).

**Step 3: Run type checks**

Run: `uv run mypy squidbot/`

Expected: `Success: no issues found`.

### Task 6: Commit changes

**Files:**
- Modify: `squidbot/core/scheduler.py`
- Modify: `tests/core/test_scheduler.py`
- Modify: `tests/core/test_cron_ops.py`
- Optional modify: `tests/adapters/tools/test_cron_tools.py`
- Add: `docs/plans/2026-02-28-scheduler-interval-validation-design.md`
- Add: `docs/plans/2026-02-28-scheduler-interval-validation-implementation-plan.md`

**Step 1: Stage files**

Run:

`git add squidbot/core/scheduler.py tests/core/test_scheduler.py tests/core/test_cron_ops.py tests/adapters/tools/test_cron_tools.py docs/plans/2026-02-28-scheduler-interval-validation-design.md docs/plans/2026-02-28-scheduler-interval-validation-implementation-plan.md`

If Task 4 is skipped, omit `tests/adapters/tools/test_cron_tools.py`.

**Step 2: Commit**

Run:

`git commit -m "fix(cron): reject non-positive every intervals"`

**Step 3: Verify clean status**

Run: `git status`

Expected: working tree clean (or only unrelated pre-existing changes).
