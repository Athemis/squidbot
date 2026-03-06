# Dashboard UI Refresh with Skeleton Tokens — Design Document

**Date:** 2026-03-05
**Status:** Approved

## Motivation

The dashboard is functionally complete but visually minimal. The current UI uses mostly unstyled HTML elements and lacks a coherent visual system across Overview, Logs, Config, and Chat.

We want a fast, consistent redesign using Skeleton + Tailwind and explicitly adopting Skeleton tokens. Visual distinctiveness from default Skeleton is not a requirement.

## Product Goal

Ship a polished, readable dashboard UI with:

- Skeleton component styling and token usage across all pages.
- Theme support for `system`, `light`, and `dark`.
- Default theme behavior set to `system`.
- Persisted user preference in `localStorage`.

## Scope

### In scope

- Add Skeleton/Tailwind setup to `web/dashboard`.
- Introduce a shared app shell and navigation styling.
- Apply Skeleton tokens/components to Overview, Logs, Config, and Chat pages.
- Add theme selector (system/light/dark) and runtime theme application.
- Keep all existing API contracts unchanged.

### Out of scope

- Backend endpoint changes.
- New dashboard features or data model changes.
- Rewriting frontend routing architecture.

## Design Decisions

1. **UI stack:** Skeleton is the primary styling system; Tailwind remains utility layer.
2. **Tokens:** Use Skeleton tokens directly for color, typography, spacing, and semantic states.
3. **Theme default:** `system` on first load.
4. **Theme persistence:** User selection persisted in `localStorage`.
5. **Theme response:** In `system` mode, react to `prefers-color-scheme` changes.
6. **Delivery strategy:** Incremental page migration in this order: Overview -> Logs -> Config -> Chat.

## Architecture

### Frontend structure

- `web/dashboard/src/App.svelte`
  - Owns shell layout, top navigation, and theme selector.
- `web/dashboard/src/lib/theme.ts` (new)
  - Theme state model (`system | light | dark`), persistence, and application helpers.
- `web/dashboard/src/lib/ui/*` (new, lightweight)
  - Reusable wrappers for repeated page patterns (cards, section headers, status chips) where useful.
- `web/dashboard/src/lib/ui/index.ts` (new)
  - Explicit barrel export for shared UI primitives.

### Styling strategy

- Install and configure Skeleton for Svelte + Tailwind pipeline.
- Define token-backed class conventions and use them consistently on all pages.
- Prefer semantic token classes over hard-coded color values.

### No backend impact

- All requests remain unchanged (`/api/overview`, `/api/logs`, `/api/config`, `/api/chat/stream`, etc.).
- Existing fetch/data logic stays intact except UI state presentation.

## UX Specification

### Global shell

- Sticky/top-aligned app header with:
  - Product title.
  - Primary nav tabs.
  - Theme selector (`system`, `light`, `dark`).
- Consistent max-width content container and spacing scale.

### Overview

- Use card surfaces for high-level metrics (started at, uptime, cron jobs).
- Use tokenized status chips for channel/session health cues.
- Keep table data structure, but improve hierarchy and spacing.

### Logs

- Add clear toolbar area for refresh/load actions.
- Use monospace-friendly surface with improved row separators and density.
- Improve loading, empty, and error visual states.

### Config

- Organize settings into clear sections with card containers.
- Improve form alignment and call-to-action hierarchy.
- Highlight restart-required notices with semantic token styling.

### Chat

- Distinct visual treatment for user and assistant messages.
- Stable composer area and better stream readability.
- Preserve existing streaming behavior.

## Theme Behavior

1. On load, read stored theme key from `localStorage`.
2. If missing, use `system`.
3. If `system`, apply current OS preference and subscribe to media-query changes.
4. If user selects `light` or `dark`, persist and apply immediately.
5. Ensure SSR-safety/defensive checks where `window` is not available in tests.

## Verification Mode Decision

The frontend test runner currently uses Vitest with `environment: "node"`.

- This redesign will keep Node-based unit tests for deterministic logic.
- UI acceptance for shell/page styling and theme interaction will be verified with a required manual QA checklist.
- A jsdom/component-test harness is out of scope for this iteration.

## Error Handling

- Theme initialization failures fall back to `system` without breaking page render.
- Invalid stored values are ignored and replaced with `system`.
- Page-level data errors continue to use existing message flows, only visual treatment changes.

## Testing Strategy

### Frontend unit tests

- Theme model tests:
  - default `system` when storage empty
  - valid value persistence
  - invalid value fallback
  - media-query reaction in `system` mode
- Existing polling/api tests remain green.

### Required manual QA checklist

- Route shell and navigation are readable and responsive on desktop/mobile.
- Theme selector applies `system`, `light`, and `dark` correctly.
- First load without stored value uses `system`.
- Stored user selection persists after reload.
- In `system` mode, changing OS theme updates the dashboard appearance.
- Chat streaming UX remains functional (send, chunked response, completion, error visibility).

### API contract non-regression checks

- Confirm frontend continues calling existing endpoints:
  - `/api/overview`
  - `/api/chat/stream`
  - `/api/bootstrap`
  - existing config/logs endpoints from current API helpers/pages
- No request payload/headers are changed outside styling/theming concerns.

### Build validation

- `npm --prefix web/dashboard run test`
- `npm --prefix web/dashboard run build`

### Project verification

- `uv run ruff check .`
- `uv run ruff format . --check`
- `uv run mypy squidbot/`
- `uv run pytest`

## Risks and Mitigations

- **Risk:** Visual regressions from broad CSS changes.
  - **Mitigation:** Migrate page-by-page and verify each route.
- **Risk:** Theme toggle introduces hydration/runtime edge cases.
  - **Mitigation:** Isolate theme logic in `lib/theme.ts` with tests.
- **Risk:** Token misuse creates inconsistent styling.
  - **Mitigation:** Use a small set of shared token patterns and reusable wrappers.

## Acceptance Criteria

- Skeleton is configured and used by dashboard UI.
- Theme selector supports `system`, `light`, and `dark`.
- Default is `system`; user choice persists across reloads.
- `system` mode reacts to runtime OS color-scheme changes.
- All four pages use consistent Skeleton/token-based styling.
- Required manual QA checklist is completed and recorded.
- Frontend API contract remains unchanged.
- Existing functional tests remain passing; frontend tests/build pass.

## Verification Matrix

| Requirement | Evidence |
|---|---|
| Theme selector has `system/light/dark` | `src/lib/theme.test.ts` + manual selector check |
| Default is `system` | `src/lib/theme.test.ts` (`readStoredTheme` fallback) + first-load manual check |
| Selection persists | `src/lib/theme.test.ts` + reload manual check |
| `system` follows OS changes | `src/lib/theme.test.ts` for media-query handling + manual OS toggle check |
| Shell/pages use Skeleton tokens | visual/manual checklist for Overview/Logs/Config/Chat |
| API contract unchanged | endpoint/path verification checklist + existing API tests pass |
| Chat stream behavior unchanged | existing stream tests + manual streaming checklist |
