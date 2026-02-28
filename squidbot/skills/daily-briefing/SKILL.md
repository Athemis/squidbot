---
name: daily-briefing
description: "Builds a compact daily brief from open work, commitments, and risks. Use when the user asks for a morning briefing, start-of-day plan, or daily focus reset."
always: false
requires: {}
---

# Daily Briefing

## Quick Workflow

1. Gather active tasks, deadlines, and pending follow-ups.
2. Select top 3 priorities for the day.
3. Highlight schedule constraints and blockers.
4. End with a short execution order.

## Output Format

- `top 3`: highest-priority outcomes for today
- `today schedule`: time-bound commitments
- `follow-ups`: items needing outbound action
- `risks`: blockers or dependency risks

## Edge Cases

- If no hard priorities exist, propose candidate top 3 with rationale.
- If too many urgent items exist, ask user to choose trade-offs.
- If context is stale, explicitly state assumptions used.
