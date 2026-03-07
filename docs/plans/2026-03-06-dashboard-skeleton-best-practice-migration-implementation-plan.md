# Dashboard Skeleton Best-Practice Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate the dashboard frontend to the current Skeleton-recommended Svelte stack and activate the official `mona` theme using documented best practices.

**Architecture:** Replace the current Tailwind v3 + Skeleton v2-style integration with Tailwind v4, `@tailwindcss/vite`, and `@skeletonlabs/skeleton-svelte`, then rewire the dashboard stylesheet/theme controller so `mona` is activated via `data-theme` while `system/light/dark` remains a mode preference. After the tooling migration, update dashboard shell/page styling where needed to align with the new Skeleton visual language and refresh packaged static assets.

**Tech Stack:** Svelte 5, Vite, Tailwind CSS v4, `@tailwindcss/vite`, `@skeletonlabs/skeleton`, `@skeletonlabs/skeleton-svelte`, Vitest

---

## Task 0: Capture migration baseline and current contract

**Files:**
- Modify: `docs/testing/dashboard-ui-manual-qa.md`
- Test: `web/dashboard/src/lib/theme.test.ts`
- Test: `web/dashboard/src/lib/chat_stream.test.ts`

**Step 1: Record baseline verification commands**

Run:

```bash
npm --prefix web/dashboard run test
npm --prefix web/dashboard run build
uv run pytest tests/adapters/test_dashboard_static_assets.py -v
```

Expected: PASS before migration changes begin.

**Step 2: Tighten manual QA checklist for migration outcome**

Add explicit checklist rows for:

- `mona` visual theme active after migration
- mode selector still behaves correctly
- packaged gateway-served assets visually match source build

**Step 3: Commit**

```bash
git add docs/testing/dashboard-ui-manual-qa.md
git commit -m "docs(dashboard-ui): expand qa checklist for skeleton migration"
```

---

## Task 1: Migrate dashboard tooling to current Skeleton stack

**Files:**
- Modify: `web/dashboard/package.json`
- Modify: `web/dashboard/package-lock.json`
- Modify: `web/dashboard/vite.config.ts`
- Delete: `web/dashboard/postcss.config.js`
- Delete or replace: `web/dashboard/tailwind.config.ts` (depending on current Skeleton/Tailwind v4 needs)

**Step 1: Write failing build expectation**

Run the current build once after removing obsolete config references but before all replacements are complete.

Run:

```bash
npm --prefix web/dashboard run build
```

Expected: FAIL during partial migration.

**Step 2: Update dependencies to best-practice stack**

- Remove obsolete packages:
  - `@skeletonlabs/tw-plugin`
  - `autoprefixer`
  - `postcss`
- Add/update:
  - `@skeletonlabs/skeleton-svelte`
  - `@tailwindcss/vite`
  - Tailwind v4-compatible versions

**Step 3: Update Vite config**

Implement doc-aligned plugin order:

```ts
import { defineConfig } from "vite"
import tailwindcss from "@tailwindcss/vite"
import { svelte } from "@sveltejs/vite-plugin-svelte"

export default defineConfig({
  plugins: [tailwindcss(), svelte()],
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"]
  }
})
```

**Step 4: Remove obsolete PostCSS pipeline**

- Delete `web/dashboard/postcss.config.js`
- Remove Vite `css.postcss` usage
- Remove any obsolete Tailwind v3-only configuration that is no longer needed

**Step 5: Run verification**

Run:

```bash
npm --prefix web/dashboard install
npm --prefix web/dashboard run test
npm --prefix web/dashboard run build
```

Expected: PASS.

**Step 6: Commit**

```bash
git add web/dashboard/package.json web/dashboard/package-lock.json web/dashboard/vite.config.ts web/dashboard/postcss.config.js web/dashboard/tailwind.config.ts
git commit -m "refactor(dashboard-ui): migrate skeleton tooling to current stack"
```

---

## Task 2: Rebuild global stylesheet around documented Skeleton imports

**Files:**
- Modify: `web/dashboard/src/app.css`
- Modify: `web/dashboard/src/main.ts`

**Step 1: Write failing build expectation for missing imports**

Run:

```bash
npm --prefix web/dashboard run build
```

Expected: FAIL while stylesheet is in an incomplete intermediate state.

**Step 2: Replace old directives with documented imports**

Top of `web/dashboard/src/app.css` should follow the Skeleton docs pattern:

```css
@import 'tailwindcss';
@import '@skeletonlabs/skeleton';
@import '@skeletonlabs/skeleton-svelte';
@import '@skeletonlabs/skeleton/themes/mona';
```

Retain only a small local section for dashboard-specific layout/preset refinements.

**Step 3: Audit and replace outdated preset class assumptions**

- Confirm current classes (`btn`, `card`, `badge`, `variant-*`, etc.) are valid in the migrated stack.
- Replace outdated class names with current Skeleton equivalents where needed.

**Step 4: Run verification**

Run:

```bash
npm --prefix web/dashboard run test
npm --prefix web/dashboard run build
```

Expected: PASS.

**Step 5: Commit**

```bash
git add web/dashboard/src/app.css web/dashboard/src/main.ts
git commit -m "refactor(dashboard-ui): align global styles with skeleton docs"
```

---

## Task 3: Rework theme controller to use `mona` correctly

**Files:**
- Modify: `web/dashboard/src/App.svelte`
- Modify: `web/dashboard/src/lib/theme.ts`
- Modify: `web/dashboard/src/lib/theme.test.ts`

**Step 1: Write failing tests for corrected theme semantics**

Add tests asserting:

- user preference is still `system | light | dark`
- the active Skeleton theme name is `mona`
- theme application no longer writes `light`/`dark` as `data-theme`

Example shape:

```ts
it("maps mode preference to mona theme application", () => {
  expect(resolveThemeName("light")).toBe("mona")
  expect(resolveThemeName("dark")).toBe("mona")
})
```

**Step 2: Run targeted tests to verify failure**

Run:

```bash
npm --prefix web/dashboard run test -- src/lib/theme.test.ts
```

Expected: FAIL before implementation is updated.

**Step 3: Implement corrected runtime behavior**

- Keep mode preference storage (`system | light | dark`)
- Set `document.documentElement.dataset.theme = "mona"`
- Implement mode handling separately from theme name handling
- Ensure the solution matches current Skeleton mode/theme guidance as closely as possible in a plain Vite app

**Step 4: Run verification**

Run:

```bash
npm --prefix web/dashboard run test -- src/lib/theme.test.ts
npm --prefix web/dashboard run build
```

Expected: PASS.

**Step 5: Commit**

```bash
git add web/dashboard/src/App.svelte web/dashboard/src/lib/theme.ts web/dashboard/src/lib/theme.test.ts
git commit -m "fix(dashboard-ui): activate mona theme through documented theme contract"
```

---

## Task 4: Update shell and page styling for the real `mona` look

**Files:**
- Modify: `web/dashboard/src/App.svelte`
- Modify: `web/dashboard/src/routes/OverviewPage.svelte`
- Modify: `web/dashboard/src/routes/LogsPage.svelte`
- Modify: `web/dashboard/src/routes/ConfigPage.svelte`
- Modify: `web/dashboard/src/routes/ChatPage.svelte`
- Modify: `web/dashboard/src/lib/ui/PageShell.svelte`
- Modify: `web/dashboard/src/lib/ui/MetricCard.svelte`
- Modify: `web/dashboard/src/lib/ui/StatusChip.svelte`
- Modify: `web/dashboard/src/lib/ui/SectionTitle.svelte`
- Modify: `docs/testing/dashboard-ui-manual-qa.md`

**Step 1: Identify outdated flat styles**

Review and replace styles that are fighting the new theme, especially:

- neutral border-heavy containers
- weak hierarchy in nav/tables/cards
- controls that do not visually match `mona`

**Step 2: Implement a `mona`-aligned pass**

- prefer Skeleton presets and color-paired token classes
- reduce plain outlined boxes
- improve navigation, cards, table surfaces, and chat presentation
- keep existing behavior intact

**Step 3: Update manual QA wording if route behavior changed visually**

Add or refine rows to reflect the migrated theme experience.

**Step 4: Run verification**

Run:

```bash
npm --prefix web/dashboard run test
npm --prefix web/dashboard run build
```

Expected: PASS.

**Step 5: Commit**

```bash
git add web/dashboard/src/App.svelte web/dashboard/src/routes/OverviewPage.svelte web/dashboard/src/routes/LogsPage.svelte web/dashboard/src/routes/ConfigPage.svelte web/dashboard/src/routes/ChatPage.svelte web/dashboard/src/lib/ui docs/testing/dashboard-ui-manual-qa.md
git commit -m "feat(dashboard-ui): restyle dashboard with mona theme best practices"
```

---

## Task 5: Refresh packaged assets and run full verification

**Files:**
- Modify: `squidbot/adapters/dashboard/static/index.html`
- Modify/Create/Delete: `squidbot/adapters/dashboard/static/assets/*`

**Step 1: Rebuild packaged assets**

Run:

```bash
python scripts/build_dashboard_assets.py
```

Expected: packaged static frontend is refreshed from the migrated source build.

**Step 2: Verify dashboard API contract remains stable**

Run:

```bash
rg "/api/(overview|bootstrap|chat/stream|config|logs)" web/dashboard/src
npm --prefix web/dashboard run test -- src/lib/api.test.ts
```

Expected: no unintended endpoint changes.

**Step 3: Run full repository verification**

Run:

```bash
uv run ruff check .
uv run ruff format . --check
uv run mypy squidbot/
uv run pytest
```

Expected: PASS.

**Step 4: Complete manual QA checklist**

Run the dashboard in browser and complete the checklist in:

```text
docs/testing/dashboard-ui-manual-qa.md
```

Expected: all relevant rows marked PASS or follow-ups captured clearly.

**Step 5: Commit**

```bash
git add squidbot/adapters/dashboard/static docs/testing/dashboard-ui-manual-qa.md
git commit -m "chore(dashboard-ui): ship mona-themed skeleton migration assets"
```
