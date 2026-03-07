# Dashboard Skeleton Redesign Design

**Date:** 2026-03-06
**Status:** Approved

## Motivation

The dashboard is now on the correct Skeleton stack and uses the `mona` theme, but it still feels too custom-shell-heavy and too flat. The main problem is not the tooling anymore; it is that the UI composition still reads like generic cards inside a hand-rolled frame instead of a confident Skeleton-native application surface.

The redesign should make the frontend look better while staying disciplined: use stock Skeleton and Tailwind patterns, reduce custom CSS, and avoid inventing a parallel design system on top of `mona`.

## Goal

Redesign `web/dashboard` so it feels like a polished operator workspace built from stock Skeleton/Tailwind primitives, with minimal custom CSS and stronger visual hierarchy across all pages.

## User Direction

The user chose:

- dense app workspace as the base direction
- more app-like controls rather than a softer documentation-style layout
- more even page quality rather than making chat the only standout page
- even less custom CSS than the current migration pass

## Scope

### In scope

- redesign the shell in `web/dashboard/src/App.svelte`
- simplify `web/dashboard/src/app.css` so it only contains minimal layout glue
- restyle the route pages to rely more heavily on Skeleton presets, cards, badges, tables, forms, and grouped controls
- improve page composition so Overview, Logs, Config, and Chat feel like one coherent app suite
- preserve current functionality and existing theme/mode behavior

### Out of scope

- backend or API changes
- new dashboard features
- custom theme generation
- heavy bespoke CSS effects or decorative one-off styling

## Design Principles

### Stock-first Skeleton

Most visual choices should live in Svelte markup via Skeleton and Tailwind classes. Prefer stock utility and preset composition over custom selectors in `app.css`.

### Operator workspace

The product should read as a compact, capable local control surface. Navigation, utility controls, status surfaces, and content panels should feel intentional and app-like rather than page-like.

### Minimal CSS

Keep global CSS limited to app-level layout concerns such as shell width, padding, and responsive stacking. Avoid page-specific visual CSS where a Skeleton/Tailwind utility combination can do the job.

### Clear hierarchy

The interface should make it obvious what is global, what is page-level, and what is actionable. Stronger grouping and structure matter more than adding visual flourishes.

## Information Architecture

### Shell

- top app region with identity, route navigation, and utility controls
- route switcher should feel like a compact control cluster rather than loose pills
- content area should feel like a workspace panel, not a floating white card inside a background

### Overview

- compact metric row first
- operational status strip second
- dense data panels for channels and sessions below
- less decorative hero treatment, more clear runtime signal

### Logs

- clearer toolbar framing
- stronger placeholder panel structure so it resembles a believable operator tool

### Config

- grouped settings panels with cleaner separation between advisory content, settings groups, and actions
- less placeholder feel through better composition, not extra ornament

### Chat

- transcript and composer should feel polished and deliberate
- stronger grouping of status, output, and prompt controls
- still part of the same dashboard family, not a visually separate product

## Implementation Approach

### App shell

Refactor `App.svelte` so the top region behaves like a proper Skeleton-native workspace header. Use stronger built-in cards, grouped controls, and compact navigation treatment. Remove dependence on custom shell classes where stock utility composition is enough.

### Shared primitives

Adjust shared UI primitives only where necessary to support the new composition. Keep them thin and token-driven.

### Route composition

Rebuild page layouts around Skeleton cards, surface presets, badges, form treatments, and table wrappers already available in the stack. Focus on hierarchy, grouping, and consistent spacing.

### CSS cleanup

Delete as much of `app.css` as possible while preserving only the layout glue that cannot be comfortably expressed inline.

## Risks and Mitigations

- **Risk:** the redesign drifts into bespoke styling again.
  - **Mitigation:** require stock Skeleton/Tailwind classes first and treat custom CSS as an exception.
- **Risk:** a denser app layout reduces readability on mobile.
  - **Mitigation:** preserve simple responsive stacking and validate at small breakpoints.
- **Risk:** visual redesign accidentally changes behavior.
  - **Mitigation:** keep existing tests, add or update tests only where markup semantics materially change, and verify frontend build/tests after the pass.

## Testing Strategy

### Frontend verification

- `npm --prefix web/dashboard run test`
- `npm --prefix web/dashboard run build`

### Follow-up packaging verification

- `python scripts/build_dashboard_assets.py`

### Project verification after redesign is complete

- `uv run ruff check .`
- `uv run ruff format . --check`
- `uv run mypy squidbot/`
- `uv run pytest`

## Acceptance Criteria

- the dashboard reads as a stronger Skeleton-native operator workspace
- `web/dashboard/src/app.css` is meaningfully smaller and mostly layout-only
- the route pages rely primarily on stock Skeleton/Tailwind composition
- all existing frontend behavior remains intact
- frontend tests/build pass after the redesign
- packaged assets can be refreshed cleanly after the redesign
