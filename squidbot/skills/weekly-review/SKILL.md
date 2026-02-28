---
name: weekly-review
description: "Runs a weekly reflection on progress, unfinished work, and next priorities. Use when the user asks for week-end review, weekly planning reset, or progress recap."
always: false
requires: {}
---

# Weekly Review

## Quick Workflow

1. Collect completed work from the week.
2. List unfinished tasks and why they carried over.
3. Extract lessons and pattern-level improvements.
4. Propose next-week priorities.

## Output Format

- `wins`: completed outcomes
- `unfinished`: open items with carry-over reason
- `lessons`: what to keep, stop, or change
- `next week priorities`: ranked focus list

## Edge Cases

- If data is incomplete, mark unknowns explicitly.
- If priorities exceed capacity, force-rank top 3.
- If no wins are visible, include small but meaningful progress markers.
