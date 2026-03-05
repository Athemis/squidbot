# Dashboard Overview Parity Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Bring `/overview` to parity with the approved dashboard design by rendering full runtime monitoring data (channels, sessions, cron summary, uptime) with adaptive polling and robust degraded-state handling.

**Architecture:** Keep the backend API contract unchanged (`GET /api/overview`) and complete parity in the Svelte frontend route by adding structured rendering and lightweight transformation helpers. Reuse existing adaptive polling behavior (`2s visible / 15s hidden`) and keep error handling deterministic and non-disruptive.

**Tech Stack:** Svelte 5, TypeScript, Vite, Vitest

---

## Task 0: Add explicit overview payload mapping helper

**Files:**
- Create: `web/dashboard/src/lib/overview.ts`
- Create: `web/dashboard/src/lib/overview.test.ts`

**Step 1: Write failing tests for payload mapping**

```ts
import { describe, expect, it } from "vitest"

import { mapOverviewPayload } from "./overview"

describe("mapOverviewPayload", () => {
  it("maps channels and sessions deterministically", () => {
    const mapped = mapOverviewPayload({
      started_at: "2026-03-05T10:00:00+00:00",
      channels: [{ name: "matrix", enabled: true, connected: false, error: "timeout" }],
      active_sessions: [
        {
          session_id: "matrix:alice",
          channel: "matrix",
          sender_id: "@alice:example.org",
          started_at: "2026-03-05T10:01:00+00:00",
          message_count: 12,
        },
      ],
      cron_jobs: 3,
    })

    expect(mapped.channels[0].statusLabel).toBe("degraded")
    expect(mapped.sessions[0].messageCount).toBe(12)
    expect(mapped.cronJobs).toBe(3)
  })
})
```

**Step 2: Run test to verify failure**

Run: `npm --prefix web/dashboard run test -- src/lib/overview.test.ts`
Expected: FAIL because helper does not exist.

**Step 3: Implement minimal mapping helper**

```ts
export function mapOverviewPayload(payload: OverviewPayload): OverviewViewModel {
  return {
    startedAt: payload.started_at,
    cronJobs: payload.cron_jobs,
    channels: payload.channels.map((channel) => ({
      ...channel,
      statusLabel: channel.connected ? "connected" : channel.error ? "degraded" : "disconnected",
    })),
    sessions: payload.active_sessions.map((session) => ({
      ...session,
      messageCount: session.message_count,
    })),
  }
}
```

**Step 4: Run tests to verify pass**

Run: `npm --prefix web/dashboard run test -- src/lib/overview.test.ts`
Expected: PASS.

**Step 5: Commit**

```bash
git add web/dashboard/src/lib/overview.ts web/dashboard/src/lib/overview.test.ts
git commit -m "test(dashboard-ui): add overview payload mapping coverage"
```

---

## Task 1: Implement full overview rendering with adaptive refresh

**Files:**
- Modify: `web/dashboard/src/routes/OverviewPage.svelte`
- Modify: `web/dashboard/src/lib/polling.ts` (only if needed for clarity)

**Step 1: Extend route state and view model usage**

- Add explicit route state: `isLoading`, `error`, `lastSuccessAt`, `overviewModel`.
- Use `mapOverviewPayload()` from Task 0.
- Keep `choosePollingIntervalMs()` and visibility-driven timer reset.

**Step 2: Render all design-required sections**

Implement route sections:
- gateway summary (started_at + computed uptime display)
- channels table (name, enabled, connected/degraded, error)
- active sessions table (session_id, channel, sender, started_at, message_count)
- cron summary (`cron_jobs` count)

**Step 3: Add degraded mode banner semantics**

- On fetch failure, keep last successful data rendered.
- Show explicit degraded banner with `lastSuccessAt` timestamp when available.

**Step 4: Verify route behavior manually via build**

Run: `npm --prefix web/dashboard run build`
Expected: PASS.

**Step 5: Commit**

```bash
git add web/dashboard/src/routes/OverviewPage.svelte web/dashboard/src/lib/polling.ts
git commit -m "feat(dashboard-ui): complete overview runtime monitoring view"
```

---

## Task 2: Verification and packaged asset refresh

**Files:**
- Modify: `squidbot/adapters/dashboard/static/index.html`
- Create/Modify: `squidbot/adapters/dashboard/static/assets/*`

**Step 1: Run frontend tests and build**

Run: `npm --prefix web/dashboard run test`
Expected: PASS.

Run: `npm --prefix web/dashboard run build`
Expected: PASS.

**Step 2: Refresh packaged static assets**

Run: `python scripts/build_dashboard_assets.py`
Expected: packaged static directory updated with current build output.

**Step 3: Run required project verification suite**

Run: `uv run ruff check .`
Expected: PASS.

Run: `uv run ruff format . --check`
Expected: PASS.

Run: `uv run mypy squidbot/`
Expected: PASS.

Run: `uv run pytest`
Expected: PASS.

**Step 4: Commit verification-safe output**

```bash
git add web/dashboard squidbot/adapters/dashboard/static
git commit -m "chore(dashboard-ui): sync packaged assets after overview parity"
```
