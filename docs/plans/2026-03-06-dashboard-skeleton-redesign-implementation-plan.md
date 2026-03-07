# Dashboard Skeleton Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign the dashboard frontend so it feels like a polished Skeleton-native operator workspace with minimal custom CSS.

**Architecture:** Keep behavior and theme plumbing intact while rebuilding the shell and route composition around stock Skeleton/Tailwind primitives. Push visual decisions into Svelte markup, shrink global CSS to layout glue, and refresh packaged assets only after frontend verification is green.

**Tech Stack:** Svelte 5, Vite, Tailwind CSS v4, `@skeletonlabs/skeleton`, `@skeletonlabs/skeleton-svelte`, Vitest

---

### Task 1: Capture the current frontend baseline

**Files:**
- Inspect: `web/dashboard/src/App.svelte`
- Inspect: `web/dashboard/src/app.css`
- Inspect: `web/dashboard/src/routes/OverviewPage.svelte`
- Inspect: `web/dashboard/src/routes/LogsPage.svelte`
- Inspect: `web/dashboard/src/routes/ConfigPage.svelte`
- Inspect: `web/dashboard/src/routes/ChatPage.svelte`

**Step 1: Review the current shell and route composition**

Identify which shell/page areas still rely on custom framing instead of stock Skeleton composition.

**Step 2: Review current CSS usage**

Mark every rule in `web/dashboard/src/app.css` as either required layout glue or redesign candidate for deletion.

**Step 3: Note test coverage that may need updates**

Inspect `web/dashboard/src/lib/ui/ui.test.ts` and any route-adjacent tests for assumptions likely to change with the redesign.

**Step 4: Commit planning artifacts if needed**

```bash
git add docs/plans/2026-03-06-dashboard-skeleton-redesign-design.md docs/plans/2026-03-06-dashboard-skeleton-redesign-implementation-plan.md
git commit -m "docs(dashboard-ui): add dashboard redesign plan"
```

### Task 2: Redesign the app shell with stock Skeleton composition

**Files:**
- Modify: `web/dashboard/src/App.svelte`
- Modify: `web/dashboard/src/app.css`
- Test: `web/dashboard/src/lib/ui/ui.test.ts`

**Step 1: Write or update a failing test for shell semantics if needed**

Prefer a minimal regression test only if heading/navigation semantics change.

**Step 2: Run the targeted test to verify the failure**

Run: `npm --prefix web/dashboard run test -- src/lib/ui/ui.test.ts`

**Step 3: Rebuild the shell markup**

Refactor the top app region into a stronger workspace header using stock Skeleton/Tailwind classes for navigation, grouped controls, and layout.

**Step 4: Remove shell-specific custom CSS that is no longer needed**

Reduce `app.css` to minimal layout glue only.

**Step 5: Re-run the targeted test**

Run: `npm --prefix web/dashboard run test -- src/lib/ui/ui.test.ts`

### Task 3: Redesign Overview as the anchor operator page

**Files:**
- Modify: `web/dashboard/src/routes/OverviewPage.svelte`
- Modify: `web/dashboard/src/lib/ui/MetricCard.svelte`
- Modify: `web/dashboard/src/lib/ui/SectionTitle.svelte`
- Modify: `web/dashboard/src/lib/ui/StatusChip.svelte`
- Test: `web/dashboard/src/lib/ui/ui.test.ts`

**Step 1: Add or update failing tests only if semantics change**

Keep tests focused on heading/alert/accessibility behavior, not styling trivia.

**Step 2: Run the targeted test to verify failure if a test was added**

Run: `npm --prefix web/dashboard run test -- src/lib/ui/ui.test.ts`

**Step 3: Recompose the Overview page**

Lead with compact metrics, then a dense status strip, then operational panels for channels and sessions using stock Skeleton cards, badges, tables, and presets.

**Step 4: Keep primitives thin**

Only update shared UI primitives if the new composition clearly benefits multiple pages.

**Step 5: Re-run the targeted test**

Run: `npm --prefix web/dashboard run test -- src/lib/ui/ui.test.ts`

### Task 4: Redesign Logs, Config, and Chat into a coherent suite

**Files:**
- Modify: `web/dashboard/src/routes/LogsPage.svelte`
- Modify: `web/dashboard/src/routes/ConfigPage.svelte`
- Modify: `web/dashboard/src/routes/ChatPage.svelte`
- Test: `web/dashboard/src/lib/ui/ui.test.ts`

**Step 1: Write or update failing tests for any changed semantics**

Cover alert/live-region or heading behavior only where markup semantics change.

**Step 2: Run the targeted test to verify failure**

Run: `npm --prefix web/dashboard run test -- src/lib/ui/ui.test.ts`

**Step 3: Rebuild Logs and Config page composition**

Use clearer toolbar bands, grouped panels, and stock Skeleton/Tailwind control treatments so placeholders feel intentional instead of temporary.

**Step 4: Rebuild Chat page composition**

Create a more polished transcript/composer/status layout using stock Skeleton surfaces, grouped controls, and stronger hierarchy while preserving stream behavior and accessibility.

**Step 5: Re-run the targeted test**

Run: `npm --prefix web/dashboard run test -- src/lib/ui/ui.test.ts`

### Task 5: Verify the redesigned frontend

**Files:**
- Verify: `web/dashboard/`

**Step 1: Run the full frontend test suite**

Run: `npm --prefix web/dashboard run test`

**Step 2: Run the frontend production build**

Run: `npm --prefix web/dashboard run build`

**Step 3: Review the final diff**

Confirm the redesign reduced custom CSS and kept the visual changes centered in Svelte markup.

**Step 4: Commit the redesign slice**

```bash
git add web/dashboard/src/App.svelte web/dashboard/src/app.css web/dashboard/src/routes/OverviewPage.svelte web/dashboard/src/routes/LogsPage.svelte web/dashboard/src/routes/ConfigPage.svelte web/dashboard/src/routes/ChatPage.svelte web/dashboard/src/lib/ui/*.svelte web/dashboard/src/lib/ui/ui.test.ts
git commit -m "feat(dashboard-ui): redesign dashboard shell and pages"
```

### Task 6: Refresh packaged assets and run repo verification

**Files:**
- Modify: `squidbot/adapters/dashboard/static/index.html`
- Modify: `squidbot/adapters/dashboard/static/assets/*`

**Step 1: Refresh packaged assets**

Run: `python scripts/build_dashboard_assets.py`

**Step 2: Run repo lint checks**

Run: `uv run ruff check .`

**Step 3: Run formatting check**

Run: `uv run ruff format . --check`

**Step 4: Run strict type checks**

Run: `uv run mypy squidbot/`

**Step 5: Run full test suite**

Run: `uv run pytest`

**Step 6: Commit packaged assets and verification-safe changes**

```bash
git add squidbot/adapters/dashboard/static docs/testing/dashboard-ui-manual-qa.md
git commit -m "chore(dashboard-ui): refresh redesigned dashboard assets"
```
