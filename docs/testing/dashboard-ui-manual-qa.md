# Dashboard UI Manual QA Checklist

Use this checklist for manual verification of the dashboard shell and theming behavior.
Mark each item `PASS` or `FAIL` and add notes for any failures.

## Test Session

- Date:
- Tester:
- Environment (OS + browser):
- Backend URL:
- Frontend command used:

## Pass/Fail Checklist

| ID | Area | Scenario | Pass Criteria | Result | Notes |
| --- | --- | --- | --- | --- | --- |
| QA-01 | Active route switching | Click each nav tab (`Overview`, `Logs`, `Config`, `Chat`) in sequence, then return to `Overview`. | The visible route content switches correctly on every click and the active tab styling follows the selected route. |  |  |
| QA-02 | Mobile shell wrapping | Resize from desktop to mobile width and back while cycling through all tabs. | Top bar controls wrap/stack without overlap, tabs stay tappable, and content area remains readable without clipped controls. |  |  |
| QA-03 | Theme selector placement and usability | On desktop and mobile widths, use the selector in each route and confirm it remains reachable. | Theme selector stays aligned in the shell controls area, remains visible when controls wrap, and can be changed without layout breakage. |  |  |
| QA-04 | Theme modes | Switch theme selector through `system`, `light`, `dark`. | Each selection immediately updates UI mode with visible appearance change and no broken or mixed theme state. |  |  |
| QA-05 | `mona` theme activation after migration | Load the dashboard after the migration build and inspect shell, cards, buttons/inputs, table surfaces, and chat panels in both light and dark modes. | Shell and content use `mona`-styled surfaces (not plain browser white/black boxes), controls show Skeleton preset styling, and cards/tables/chat surfaces share a consistent tonal or filled surface language in both modes. |  |  |
| QA-06 | System default on first load | Clear local storage key `squidbot-dashboard-theme` and reload. | Theme selector defaults to `system` and no invalid theme state appears. |  |  |
| QA-07 | Persisted selection | Select `light`, reload, then select `dark`, reload. | Last selected non-system mode is preserved after each reload. |  |  |
| QA-08 | Mode selector behavior after migration | Switch the selector through `system`, `light`, `dark` repeatedly while moving between routes and resizing from desktop to mobile width. | The selector keeps the correct selected value, continues to change modes immediately, and remains usable across route changes and responsive layout shifts. |  |  |
| QA-09 | OS theme reaction in system mode | Set selector to `system`, then toggle OS/browser preferred color scheme. | Dashboard updates to match OS theme without manual refresh. |  |  |
| QA-10 | Chat stream UX regression | Open Chat tab and send a prompt that streams multiple chunks. | Streamed content appears progressively inside the styled response panel, completion state is clear, and input controls remain visible with the expected disabled/active state during streaming. |  |  |
| QA-11 | Chat send enable/disable behavior | In Chat, verify with empty prompt, non-empty prompt, and while request is in-flight. | Send stays disabled for blank prompt, enables for non-empty prompt, and input/send controls show disabled state while sending. |  |  |
| QA-12 | Chat progressive chunk rendering | Send a prompt that returns multiple streamed chunks and observe output container live. | Response text grows incrementally during stream (not only at end), with streaming state indicator visible. |  |  |
| QA-13 | Chat done-frame completion behavior | Send a normal prompt and wait for stream completion. | Stream transitions from streaming to complete state, sending status clears, and final transcript remains visible. |  |  |
| QA-14 | Chat visible stream error state | Trigger a failing stream request (network interruption or backend error). | Chat page shows explicit error alert/state and allows retry after failure. |  |  |
| QA-15 | Chat nonce refresh recovery | Use devtools or a temporary backend stub to force the first `/api/chat/stream` request to return `403` with `{"error":{"code":"INVALID_NONCE"}}`, then allow the next retry to succeed. | Network panel shows initial `403` chat request, followed by `/api/bootstrap`, followed by a retried `/api/chat/stream`; the user sees streaming start successfully without reloading or manually resetting state. |  |  |
| QA-16 | API endpoint contract spot-check | Exercise Overview and Chat while monitoring network requests, then visit Logs/Config and confirm no unexpected API calls are introduced. | Observed requests remain within existing contract (`/api/overview`, `/api/bootstrap`, `/api/chat/stream`, plus current config/logs helper paths if invoked) and no new endpoint paths are introduced. |  |  |
| QA-17 | Packaged asset parity after migration | Compare the source Vite build (`npm --prefix web/dashboard run dev` or preview) against the gateway-served packaged dashboard for the same revision. | Shell layout, active theme appearance, navigation styling, cards/tables/chat surfaces, and tonal preset treatments match with no obvious stale CSS/JS or missing themed components between the two builds. |  |  |
| QA-18 | Logs toolbar/action clarity | Open `Logs` and review filter controls plus action buttons at desktop and mobile widths. | Toolbar controls are visually grouped, filled/tonal/outlined button priority is obvious, and controls remain readable when wrapping. |  |  |
| QA-19 | Logs state placeholder readability | On `Logs`, switch through loading, empty, and error state previews. | Each state has distinct styling and clear explanatory copy with no clipped text in either theme. |  |  |
| QA-20 | Config section grouping and hierarchy | Open `Config` and inspect Runtime, Channel Configuration, and Apply Changes sections. | Sections are visually separated with themed cards, related controls stay grouped, and the primary action stands out from secondary actions. |  |  |
| QA-21 | Config restart-required banner visibility | Open `Config` in both light and dark themes. | Restart-required banner remains visible, legible, and clearly distinct from body content in both themes. |  |  |

## Outcome

- Overall status:
- Follow-up issues:
  - Complete QA-01..QA-21 against a running `squidbot gateway` dashboard instance.
