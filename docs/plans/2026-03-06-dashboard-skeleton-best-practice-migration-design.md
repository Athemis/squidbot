# Dashboard Skeleton Best-Practice Migration Design

**Date:** 2026-03-06
**Status:** Approved

## Motivation

The current dashboard styling work improved structure but does not follow the current Skeleton setup recommendations. The frontend still uses an older Skeleton/Tailwind integration model (`@skeletonlabs/tw-plugin`, Tailwind v3, PostCSS pipeline, generic `light`/`dark` theme values) instead of the documented best-practice stack.

This mismatch prevents the dashboard from benefiting from Skeleton's intended theme system and explains why the result looks flatter and less refined than the official Skeleton examples and theme generator output.

## Goal

Migrate the dashboard frontend to the current Skeleton best-practice stack and use the official `mona` theme as the active visual language for both light and dark mode handling.

## Scope

### In scope

- Migrate `web/dashboard` from the current Tailwind v3 + Skeleton v2-style setup to the current Skeleton-recommended stack.
- Replace the old plugin/PostCSS configuration with the Vite + Tailwind v4 setup recommended by Skeleton docs.
- Add the official Skeleton Svelte package and use the documented global stylesheet imports.
- Register and activate `mona` as the app theme via `data-theme`.
- Rework theme switching so UI mode behavior is consistent with Skeleton guidance.
- Update dashboard shell and page styling to use Skeleton presets/tokens idiomatically under the new stack.
- Refresh packaged frontend assets and verification docs.

### Out of scope

- Backend API changes.
- New dashboard features.
- Custom theme generation.
- A broad migration to many Skeleton framework components unless a specific component clearly improves the current UI.

## Current State

- `web/dashboard/package.json` uses `@skeletonlabs/skeleton` `^2.11.0` and `@skeletonlabs/tw-plugin`.
- `web/dashboard/vite.config.ts` uses a PostCSS pipeline and does not use `@tailwindcss/vite`.
- `web/dashboard/src/app.css` uses `@tailwind` directives and custom utility layers rather than the current doc-recommended imports.
- `web/dashboard/src/App.svelte` sets `data-theme` values of `light` and `dark`, which do not correspond to registered Skeleton theme names.
- The current setup therefore does not correctly activate official Skeleton preset themes.

## Recommended Approach

Adopt the current documented Skeleton stack for Vite + Svelte:

- `@skeletonlabs/skeleton`
- `@skeletonlabs/skeleton-svelte`
- `tailwindcss` v4
- `@tailwindcss/vite`
- Global stylesheet imports:
  - `@import 'tailwindcss';`
  - `@import '@skeletonlabs/skeleton';`
  - `@import '@skeletonlabs/skeleton-svelte';`
  - `@import '@skeletonlabs/skeleton/themes/mona';`

Then activate `mona` via `data-theme="mona"` and build the mode/theme controller around that documented mechanism.

## Theme Decision

The user selected:

- **Approach:** full best-practice migration (Option A)
- **Theme:** `mona`

Interpretation for mode support:

- `mona` is the single Skeleton theme identity.
- `system/light/dark` remains a user-facing mode preference for browser color-scheme behavior.
- The app keeps `data-theme="mona"` and uses Skeleton/Tailwind mode guidance rather than pretending `light` and `dark` are theme names.

## Architecture

### Tooling layer

- Remove obsolete dependencies and config:
  - `@skeletonlabs/tw-plugin`
  - `autoprefixer`
  - `postcss`
  - Tailwind v3-specific setup
- Add/update:
  - `@skeletonlabs/skeleton-svelte`
  - `@tailwindcss/vite`
  - Tailwind v4-compatible configuration

### Stylesheet layer

- Replace `@tailwind base/components/utilities` with Skeleton's documented `@import` stack.
- Keep a small local stylesheet section only for dashboard-specific layout/preset refinements.
- Prefer Skeleton presets and design tokens over hand-rolled neutral classes when possible.

### Runtime theme handling

- `data-theme` should always be set to `mona`.
- The stored user preference remains `system | light | dark`.
- Mode switching should align with current Skeleton guidance for dark mode, rather than swapping arbitrary theme names.
- The implementation should avoid the old `data-theme="light"|"dark"` contract.

### Component usage

- Continue using semantic HTML + Tailwind/Skeleton token classes where sufficient.
- Introduce Skeleton Svelte components selectively only if they materially improve navigation, segmented controls, or form controls.
- Do not rewrite working pages just to maximize component count.

## UI Direction

The desired look is the official Skeleton `mona` aesthetic, not a neutralized approximation.

Concretely:

- stronger background contrast
- richer surface hierarchy
- better preset styling for buttons/cards/badges/inputs
- typography and spacing that feel closer to Skeleton showcase examples
- reduced plain-border/plain-white-box appearance

## Testing Strategy

### Frontend verification

- `npm --prefix web/dashboard run test`
- `npm --prefix web/dashboard run build`

### Project verification

- `python scripts/build_dashboard_assets.py`
- `uv run ruff check .`
- `uv run ruff format . --check`
- `uv run mypy squidbot/`
- `uv run pytest`

### Manual QA

Update the dashboard manual QA checklist to include:

- `mona` theme visibly active after migration
- mode switching still works correctly
- no regressions in overview/chat/config/logs flows
- packaged asset refresh confirmed visually in running gateway

## Risks and Mitigations

- **Risk:** Tailwind v4 migration changes utility behavior.
  - **Mitigation:** migrate tooling first, verify build/tests immediately, then adjust styling layer.
- **Risk:** current Skeleton class names/presets may differ under the modern stack.
  - **Mitigation:** audit key classes during migration and replace outdated patterns systematically.
- **Risk:** theme mode logic conflicts with Skeleton's documented dark-mode handling.
  - **Mitigation:** simplify the controller so `data-theme` uses `mona` only and mode toggling is handled independently.
- **Risk:** packaged dashboard assets drift from source build.
  - **Mitigation:** keep asset rebuild as a required final verification step.

## Acceptance Criteria

- `web/dashboard` uses the current Skeleton-recommended package/config stack.
- `mona` is registered and activated through the documented stylesheet + `data-theme` path.
- The old `@skeletonlabs/tw-plugin`/PostCSS setup is removed.
- Dashboard UI visibly matches the richer Skeleton theme language better than the current flat version.
- Frontend tests/build and full project verification pass.
- Packaged dashboard assets are refreshed.
