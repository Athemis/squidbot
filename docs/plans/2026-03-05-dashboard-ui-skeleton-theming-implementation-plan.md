# Dashboard UI Refresh with Skeleton Tokens Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the dashboard frontend to a polished Skeleton-based UI with token-driven styling and a persisted `system/light/dark` theme selector.

**Architecture:** Keep existing backend APIs untouched and implement all changes in the Svelte frontend. Add Skeleton/Tailwind wiring, introduce a small theme module (`system` default + localStorage persistence), refactor app shell styling, then migrate pages incrementally (Overview -> Logs -> Config -> Chat) to shared visual patterns.

**Tech Stack:** Svelte 5, TypeScript, Tailwind CSS, Skeleton, Vitest, Vite

---

## Task 0: Add Skeleton + Tailwind wiring to dashboard frontend

**Files:**
- Modify: `web/dashboard/package.json`
- Modify: `web/dashboard/vite.config.ts`
- Create: `web/dashboard/postcss.config.js`
- Create: `web/dashboard/tailwind.config.ts`
- Create: `web/dashboard/src/app.css`
- Modify: `web/dashboard/src/main.ts`
- Create: `docs/testing/dashboard-ui-manual-qa.md`

**Step 1: Write a required manual QA checklist document**

Create `docs/testing/dashboard-ui-manual-qa.md` with explicit pass/fail items for:
- shell responsiveness
- theme selector behavior (`system/light/dark`)
- first-load `system` default
- persisted selection after reload
- OS theme change reaction in `system`
- chat stream UX regression check
- API endpoint contract spot-check

**Step 2: Run tests/build to verify baseline**

Run: `npm --prefix web/dashboard run test`
Expected: PASS baseline before dependency changes.

Run: `npm --prefix web/dashboard run build`
Expected: PASS baseline before dependency changes.

**Step 3: Implement Skeleton/Tailwind setup + keep Node test environment**

- Add required dependencies for Tailwind/Skeleton.
- Configure Vite/Tailwind/Skeleton integration files.
- Create `src/app.css` with Tailwind directives and Skeleton theme import/config.
- Import `./app.css` in `src/main.ts`.
- Keep Vitest runtime as `environment: "node"` for this iteration.

**Step 4: Run tests/build to verify pass**

Run: `npm --prefix web/dashboard run test`
Expected: PASS.

Run: `npm --prefix web/dashboard run build`
Expected: PASS.

**Step 5: Commit**

```bash
git add web/dashboard/package.json web/dashboard/vite.config.ts web/dashboard/postcss.config.js web/dashboard/tailwind.config.ts web/dashboard/src/app.css web/dashboard/src/main.ts docs/testing/dashboard-ui-manual-qa.md
git commit -m "feat(dashboard-ui): wire skeleton and tailwind styling stack"
```

---

## Task 1: Implement theme model (system default + persistence)

**Files:**
- Create: `web/dashboard/src/lib/theme.ts`
- Create: `web/dashboard/src/lib/theme.test.ts`
- Modify: `web/dashboard/src/App.svelte`

**Step 1: Write failing tests for theme behavior**

```ts
import { describe, expect, it } from "vitest"

import {
  DEFAULT_THEME,
  readStoredTheme,
  writeStoredTheme,
  createSystemThemeObserver,
  normalizeTheme,
  resolveAppliedTheme,
} from "./theme"

describe("theme", () => {
  it("defaults to system", () => {
    expect(DEFAULT_THEME).toBe("system")
  })

  it("normalizes invalid values to system", () => {
    expect(normalizeTheme("invalid")).toBe("system")
  })

  it("resolves system using prefers dark", () => {
    expect(resolveAppliedTheme("system", true)).toBe("dark")
  })

  it("falls back to system for invalid stored value", () => {
    expect(readStoredTheme(() => "broken")).toBe("system")
  })

  it("persists selected theme", () => {
    let stored = ""
    writeStoredTheme("dark", (value) => {
      stored = value
    })
    expect(stored).toBe("dark")
  })

  it("subscribes to system theme changes only in system mode", () => {
    const calls: Array<(prefersDark: boolean) => void> = []
    const unsubscribe = createSystemThemeObserver((cb) => {
      calls.push(cb)
      return () => undefined
    }, () => undefined)
    expect(calls).toHaveLength(1)
    unsubscribe()
  })
})
```

**Step 2: Run test to verify failure**

Run: `npm --prefix web/dashboard run test -- src/lib/theme.test.ts`
Expected: FAIL because `theme.ts` does not exist.

**Step 3: Implement minimal theme module + shell integration**

- Add typed theme union: `"system" | "light" | "dark"`.
- Add helpers for normalization, storage read/write, and applied-theme resolution.
- Add theme selector UI to `App.svelte`.
- On mount: load storage, apply resolved theme, subscribe to system-theme changes in `system` mode.

**Step 4: Run tests/build to verify pass**

Run: `npm --prefix web/dashboard run test -- src/lib/theme.test.ts`
Expected: PASS.

Run: `npm --prefix web/dashboard run build`
Expected: PASS.

**Step 5: Commit**

```bash
git add web/dashboard/src/lib/theme.ts web/dashboard/src/lib/theme.test.ts web/dashboard/src/App.svelte
git commit -m "feat(dashboard-ui): add persisted system-light-dark theme selector"
```

---

## Task 2: Create shared Skeleton/token UI primitives

**Files:**
- Create: `web/dashboard/src/lib/ui/PageShell.svelte`
- Create: `web/dashboard/src/lib/ui/MetricCard.svelte`
- Create: `web/dashboard/src/lib/ui/StatusChip.svelte`
- Create: `web/dashboard/src/lib/ui/SectionTitle.svelte`
- Create: `web/dashboard/src/lib/ui/index.ts`
- Create: `web/dashboard/src/lib/ui/ui.test.ts`

**Step 1: Write failing component tests**

```ts
import { describe, expect, it } from "vitest"

describe("ui primitives", () => {
  it("exports named primitives from index", async () => {
    const module = await import("./index")
    expect(module.PageShell).toBeDefined()
    expect(module.MetricCard).toBeDefined()
    expect(module.StatusChip).toBeDefined()
    expect(module.SectionTitle).toBeDefined()
  })
})
```

**Step 2: Run test to verify failure**

Run: `npm --prefix web/dashboard run test -- src/lib/ui/ui.test.ts`
Expected: FAIL because files/exports do not exist.

**Step 3: Implement minimal reusable primitives**

- Build small wrappers with Skeleton token classes for repeated layout and semantic status styles.
- Keep component API narrow and practical (avoid over-abstraction).

**Step 4: Run tests/build to verify pass**

Run: `npm --prefix web/dashboard run test -- src/lib/ui/ui.test.ts`
Expected: PASS.

Run: `npm --prefix web/dashboard run build`
Expected: PASS.

**Step 5: Commit**

```bash
git add web/dashboard/src/lib/ui
git commit -m "feat(dashboard-ui): add shared skeleton-token ui primitives"
```

---

## Task 3: Refactor app shell and navigation styling

**Files:**
- Modify: `web/dashboard/src/App.svelte`
- Modify: `web/dashboard/src/app.css`

**Step 1: Add explicit manual QA steps for shell and nav**

Extend `docs/testing/dashboard-ui-manual-qa.md` with pass/fail checks for:
- active route switching across all tabs
- mobile layout wrapping
- theme selector placement and usability

**Step 2: Run build baseline**

Run: `npm --prefix web/dashboard run build`
Expected: PASS before refactor.

**Step 3: Implement shell redesign**

- Add top app bar, tokenized nav tabs, spacing container, and theme selector placement.
- Ensure mobile-friendly wrapping/stacking behavior.
- Preserve current route switching logic.

**Step 4: Run tests/build to verify pass**

Run: `npm --prefix web/dashboard run test`
Expected: PASS.

Run: `npm --prefix web/dashboard run build`
Expected: PASS.

**Step 5: Commit**

```bash
git add web/dashboard/src/App.svelte web/dashboard/src/app.css
git commit -m "feat(dashboard-ui): redesign shell navigation with skeleton tokens"
```

---

## Task 4: Migrate Overview page to tokenized cards/tables

**Files:**
- Modify: `web/dashboard/src/routes/OverviewPage.svelte`
- Modify: `web/dashboard/src/lib/overview.ts` (only if mapping output needs style-friendly fields)
- Test: `web/dashboard/src/lib/overview.test.ts`

**Step 1: Write concrete mapping regression test**

```ts
it("maps status labels for tokenized badges", () => {
  // assert status label values remain deterministic for badge mapping
})
```

**Step 2: Run focused tests to verify failure**

Run: `npm --prefix web/dashboard run test -- src/lib/overview.test.ts`
Expected: FAIL before code is updated for the new assertion.

**Step 3: Implement Overview UI refresh**

- Use metric cards, improved tables, status chips, and consistent spacing.
- Keep existing polling and degraded-mode logic unchanged.

**Step 4: Run tests/build to verify pass**

Run: `npm --prefix web/dashboard run test -- src/lib/overview.test.ts`
Expected: PASS.

Run: `npm --prefix web/dashboard run build`
Expected: PASS.

**Step 5: Commit**

```bash
git add web/dashboard/src/routes/OverviewPage.svelte web/dashboard/src/lib/overview.ts web/dashboard/src/lib/overview.test.ts
git commit -m "feat(dashboard-ui): restyle overview with cards tables and status chips"
```

---

## Task 5: Implement Logs and Config page visual refresh

**Files:**
- Modify: `web/dashboard/src/routes/LogsPage.svelte`
- Modify: `web/dashboard/src/routes/ConfigPage.svelte`

**Step 1: Add explicit manual QA checks for Logs and Config pages**

Update `docs/testing/dashboard-ui-manual-qa.md` with pass/fail checks for:
- logs toolbar/actions visual clarity
- logs empty/error/loading state readability
- config section grouping and action hierarchy
- restart-required banner visibility in both themes

**Step 2: Run build baseline**

Run: `npm --prefix web/dashboard run build`
Expected: PASS baseline.

**Step 3: Implement Logs/Config page styling**

- Logs: toolbar layout, list/table surface, readable empty/error states.
- Config: structured sections, form spacing, action button hierarchy.
- Use Skeleton tokens consistently.

**Step 4: Run tests/build to verify pass**

Run: `npm --prefix web/dashboard run test`
Expected: PASS.

Run: `npm --prefix web/dashboard run build`
Expected: PASS.

**Step 5: Commit**

```bash
git add web/dashboard/src/routes/LogsPage.svelte web/dashboard/src/routes/ConfigPage.svelte
git commit -m "feat(dashboard-ui): restyle logs and config pages with skeleton tokens"
```

---

## Task 6: Implement Chat page visual refresh

**Files:**
- Modify: `web/dashboard/src/routes/ChatPage.svelte`

**Step 1: Add explicit manual QA checks for chat non-regression**

Update `docs/testing/dashboard-ui-manual-qa.md` with pass/fail checks for:
- send action disabled/enabled behavior
- streaming chunks render progressively
- done frame completion behavior
- visible error state when stream fails

**Step 2: Run build baseline**

Run: `npm --prefix web/dashboard run build`
Expected: PASS baseline.

**Step 3: Implement Chat UI refresh**

- Add tokenized message display surfaces and input/action layout.
- Preserve stream parsing and nonce retry logic exactly.
- Improve sending/error state visibility.

**Step 4: Run tests/build to verify pass**

Run: `npm --prefix web/dashboard run test`
Expected: PASS.

Run: `npm --prefix web/dashboard run build`
Expected: PASS.

**Step 5: Commit**

```bash
git add web/dashboard/src/routes/ChatPage.svelte
git commit -m "feat(dashboard-ui): restyle chat stream page with skeleton tokens"
```

---

## Task 7: Refresh packaged static assets and run full verification

**Files:**
- Modify: `squidbot/adapters/dashboard/static/index.html`
- Modify/Create: `squidbot/adapters/dashboard/static/assets/*`

**Step 1: Run frontend suite and build**

Run: `npm --prefix web/dashboard run test`
Expected: PASS.

Run: `npm --prefix web/dashboard run build`
Expected: PASS.

**Step 2: Copy built assets into package path**

Run: `python scripts/build_dashboard_assets.py`
Expected: Packaged static files updated.

**Step 3: Run project verification suite**

Run: `uv run ruff check .`
Expected: PASS.

Run: `uv run ruff format . --check`
Expected: PASS.

Run: `uv run mypy squidbot/`
Expected: PASS.

Run: `uv run pytest`
Expected: PASS.

**Step 4: Verify frontend API contract unchanged**

Run: `rg "/api/(overview|bootstrap|chat/stream|config|logs)" web/dashboard/src`
Expected: Same endpoint set as pre-redesign; no new API paths introduced.

Run: `npm --prefix web/dashboard run test -- src/lib/api.test.ts`
Expected: PASS.

**Step 5: Execute manual QA checklist and record outcomes**

Complete `docs/testing/dashboard-ui-manual-qa.md` with date, environment, and pass/fail notes.

**Step 6: Commit**

```bash
git add web/dashboard squidbot/adapters/dashboard/static docs/testing/dashboard-ui-manual-qa.md
git commit -m "chore(dashboard-ui): ship skeleton-token themed dashboard assets"
```
