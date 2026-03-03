# Design: Fix Cron Deletion Race Condition (In-Process Lock)

## Problem

Issue #62 reports that a deleted cron job can still execute later.
The root cause is a stale read-modify-write window:

1. `CronScheduler._tick()` loads all jobs once.
2. A concurrent tool call (for example `cron_remove`) loads and saves an updated list.
3. The scheduler later saves its stale in-memory list and overwrites the deletion.

This is possible because cron state is persisted as a full list in `jobs.json` and both scheduler and tools perform whole-list writes.

## Scope and Constraints

- Fix only in-process concurrency (single gateway process).
- Do not add cross-process optimistic locking or file-level versioning.
- Keep existing cron storage format (`cron/jobs.json`) unchanged.
- Preserve current tool and scheduler external behavior.

This matches expected usage where simultaneous edits via separate CLI processes are unlikely.

## Selected Approach

Use a shared `asyncio.Lock` for all in-process cron mutations.

### Why this approach

- Minimal surface-area change.
- Deterministic and easy to reason about.
- No migration or persistence schema changes.
- Eliminates stale overwrite races between scheduler and tool mutations in the same process.

### Alternatives considered

- Merge-on-save in scheduler: more complex conflict logic, higher regression risk.
- Versioned CAS persistence: strongest correctness, but unnecessary for in-process-only requirement.

## Architecture

### New synchronization primitive

- Create one shared `asyncio.Lock` in gateway runtime wiring.
- Pass it to:
  - `CronScheduler`
  - context cron tools (`CronAddTool`)
  - global cron tools (`CronRemoveTool`, `CronSetEnabledTool`)

### Scheduler behavior

- `CronScheduler._tick()` runs load-check-execute-save while holding the shared lock.
- This prevents overlapping tool-based read-modify-write operations from interleaving with a tick.

### Tool behavior

- Mutating tools (`cron_add`, `cron_remove`, `cron_set_enabled`) run their own load-modify-save cycle while holding the same lock.
- Read-only tool (`cron_list`) remains unlocked.

## Data Flow

1. A mutating operation starts (scheduler tick or tool call).
2. It acquires the shared lock.
3. It performs load -> mutate -> save on cron jobs.
4. It releases the lock.
5. Another operation may proceed.

Result: no stale list can be saved over a newer mutation within the same process.

## Error Handling

- Keep current semantics:
  - tools return `ToolResult(is_error=True, ...)` on failures.
  - scheduler swallows callback/storage exceptions so the loop continues.
- Lock usage must not change user-visible error formats.

## Testing Strategy

Follow TDD with a regression test that would fail without synchronization:

- Start a scheduler tick that holds execution mid-tick.
- Attempt `cron_remove` concurrently.
- Verify remove waits and final persisted state still reflects deletion.

Also keep existing cron tool tests green to confirm no behavioral regressions.

## Risks and Trade-offs

- While a tick is executing due jobs, mutating tool calls are serialized behind the lock.
- This can delay cron edits briefly under heavy due-job workload.
- Trade-off is acceptable for correctness and simplicity.

## Non-Goals

- Cross-process conflict prevention between gateway and standalone CLI commands.
- Changes to cron job schema or migration logic.
- Broader scheduler redesign.
