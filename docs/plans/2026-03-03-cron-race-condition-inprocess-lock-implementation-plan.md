# Cron Race Condition In-Process Lock Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent deleted/updated cron jobs from being overwritten by stale scheduler saves inside a single running gateway process.

**Architecture:** Introduce one shared `asyncio.Lock` for all in-process cron mutations. Wire the same lock through gateway setup into `CronScheduler` and mutating cron tools so each load-modify-save cycle is serialized. Keep persistence format and public tool behavior unchanged.

**Tech Stack:** Python 3.14, asyncio, pytest, squidbot cron scheduler/tools.

---

### Task 1: Add a failing regression test for scheduler/tool interleaving

**Files:**
- Modify: `tests/adapters/tools/test_cron_tools.py`
- Test: `tests/adapters/tools/test_cron_tools.py`

**Step 1: Write failing async regression test**

Add a test that:
- sets up shared storage with one due job and one removable job,
- starts `CronScheduler._tick()` with a blocking `on_due`,
- calls `CronRemoveTool.execute()` concurrently,
- asserts the remove call must wait until tick finishes,
- verifies removed job is absent in final persisted list.

**Step 2: Run only the new test and confirm RED**

Run: `uv run pytest tests/adapters/tools/test_cron_tools.py::TestCronToolConcurrency::test_remove_waits_for_scheduler_tick_and_persists_deletion -v`

Expected: FAIL because no shared lock exists yet.

### Task 2: Add lock support to scheduler

**Files:**
- Modify: `squidbot/core/scheduler.py`
- Test: `tests/adapters/tools/test_cron_tools.py`

**Step 1: Extend constructor with optional mutation lock**

Update `CronScheduler.__init__` to accept an optional `asyncio.Lock` and store it.

**Step 2: Serialize `_tick()` when lock is provided**

Wrap existing tick logic in a helper and guard it with:
- direct execution when lock is `None`,
- `async with lock` when lock exists.

**Step 3: Re-run failing regression test**

Run: `uv run pytest tests/adapters/tools/test_cron_tools.py::TestCronToolConcurrency::test_remove_waits_for_scheduler_tick_and_persists_deletion -v`

Expected: still FAIL (mutating tools not synchronized yet).

### Task 3: Add lock support to mutating cron tools

**Files:**
- Modify: `squidbot/adapters/tools/cron.py`
- Test: `tests/adapters/tools/test_cron_tools.py`

**Step 1: Add optional lock dependency to mutating tool constructors**

Update:
- `CronAddTool`
- `CronRemoveTool`
- `CronSetEnabledTool`

to accept `mutation_lock: asyncio.Lock | None = None`.

**Step 2: Guard load-modify-save with lock**

In each mutating tool:
- if no lock is configured, keep current path,
- if lock exists, perform load-modify-save under `async with mutation_lock`.

**Step 3: Thread lock through factory helpers**

Update:
- `build_global_cron_tools(...)`
- `build_context_cron_tools(...)`

to accept/pass the same optional lock.

**Step 4: Re-run regression test (GREEN target)**

Run: `uv run pytest tests/adapters/tools/test_cron_tools.py::TestCronToolConcurrency::test_remove_waits_for_scheduler_tick_and_persists_deletion -v`

Expected: PASS.

### Task 4: Wire shared lock in gateway composition root

**Files:**
- Modify: `squidbot/cli/gateway.py`
- Test: `tests/adapters/tools/test_cron_tools.py`

**Step 1: Create one shared lock in runtime setup**

In gateway startup path, create `cron_mutation_lock = asyncio.Lock()`.

**Step 2: Pass lock to tool builders and scheduler**

Ensure the same lock instance is used by:
- `build_global_cron_tools(...)` in `_make_agent_loop`,
- `build_context_cron_tools(...)` in channel loops,
- `CronScheduler(...)` in `_run_gateway`.

**Step 3: Run cron tool + scheduler tests**

Run: `uv run pytest tests/adapters/tools/test_cron_tools.py tests/core/test_scheduler.py -q`

Expected: PASS.

### Task 5: Full verification

**Files:**
- Verify only

**Step 1: Lint**

Run: `uv run ruff check .`

Expected: no errors.

**Step 2: Format check**

Run: `uv run ruff format . --check`

Expected: no files need formatting.

**Step 3: Tests**

Run: `uv run pytest`

Expected: PASS.

### Task 6: Prepare commit (when requested)

**Files:**
- Modify: `squidbot/core/scheduler.py`
- Modify: `squidbot/adapters/tools/cron.py`
- Modify: `squidbot/cli/gateway.py`
- Modify: `tests/adapters/tools/test_cron_tools.py`
- Add: `docs/plans/2026-03-03-cron-race-condition-inprocess-lock-design.md`
- Add: `docs/plans/2026-03-03-cron-race-condition-inprocess-lock-implementation-plan.md`

**Step 1: Review diff**

Run: `git diff -- squidbot/core/scheduler.py squidbot/adapters/tools/cron.py squidbot/cli/gateway.py tests/adapters/tools/test_cron_tools.py docs/plans/2026-03-03-cron-race-condition-inprocess-lock-design.md docs/plans/2026-03-03-cron-race-condition-inprocess-lock-implementation-plan.md`

**Step 2: Commit once explicitly requested**

Run (example): `git commit -m "fix(cron): serialize scheduler and cron tool mutations"`
