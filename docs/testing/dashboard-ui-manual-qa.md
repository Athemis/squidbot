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
| QA-04 | Theme modes | Switch theme selector through `system`, `light`, `dark`. | Each selection immediately updates UI theme with visible mode change. |  |  |
| QA-05 | System default on first load | Clear local storage key `squidbot-dashboard-theme` and reload. | Theme selector defaults to `system` and no invalid theme state appears. |  |  |
| QA-06 | Persisted selection | Select `light`, reload, then select `dark`, reload. | Last selected non-system theme is preserved after each reload. |  |  |
| QA-07 | OS theme reaction in system mode | Set selector to `system`, then toggle OS/browser preferred color scheme. | Dashboard updates to match OS theme without manual refresh. |  |  |
| QA-08 | Chat stream UX regression | Open Chat tab and send a prompt that streams multiple chunks. | Streamed content appears progressively, completion state is clear, and input controls remain usable. |  |  |
| QA-09 | Chat send enable/disable behavior | In Chat, verify with empty prompt, non-empty prompt, and while request is in-flight. | Send stays disabled for blank prompt, enables for non-empty prompt, and input/send controls show disabled state while sending. |  |  |
| QA-10 | Chat progressive chunk rendering | Send a prompt that returns multiple streamed chunks and observe output container live. | Response text grows incrementally during stream (not only at end), with streaming state indicator visible. |  |  |
| QA-11 | Chat done-frame completion behavior | Send a normal prompt and wait for stream completion. | Stream transitions from streaming to complete state, sending status clears, and final transcript remains visible. |  |  |
| QA-12 | Chat visible stream error state | Trigger a failing stream request (network interruption or backend error). | Chat page shows explicit error alert/state and allows retry after failure. |  |  |
| QA-13 | Chat nonce refresh recovery | Trigger stale nonce behavior (`403` with `INVALID_NONCE`) for chat stream request. | Client refreshes nonce via `/api/bootstrap`, retries automatically, and stream continues without manual nonce reset. |  |  |
| QA-14 | API endpoint contract spot-check | Exercise Overview and Chat while monitoring network requests, then visit Logs/Config and confirm no unexpected API calls are introduced. | Observed requests remain within existing contract (`/api/overview`, `/api/bootstrap`, `/api/chat/stream`, plus current config/logs helper paths if invoked) and no new endpoint paths are introduced. |  |  |
| QA-15 | Logs toolbar/action clarity | Open `Logs` and review filter controls plus action buttons at desktop and mobile widths. | Toolbar controls are visually grouped, action priority is obvious, and controls remain readable when wrapping. |  |  |
| QA-16 | Logs state placeholder readability | On `Logs`, switch through loading, empty, and error state previews. | Each state has distinct styling and clear explanatory copy with no clipped text in either theme. |  |  |
| QA-17 | Config section grouping and hierarchy | Open `Config` and inspect Runtime, Channel Configuration, and Apply Changes sections. | Sections are visually separated, related controls stay grouped, and primary action stands out from secondary actions. |  |  |
| QA-18 | Config restart-required banner visibility | Open `Config` in both light and dark themes. | Restart-required banner remains visible, legible, and clearly distinct from body content in both themes. |  |  |

## Outcome

- Overall status: Pending manual execution (not run in this CLI session)
- Follow-up issues:
  - Complete QA-01..QA-18 against a running `squidbot gateway` dashboard instance.
