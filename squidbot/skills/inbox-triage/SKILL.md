---
name: inbox-triage
description: "Prioritizes inbox items by urgency, impact, and effort and proposes clear next actions. Use when the user asks to process inbox backlog, identify urgent messages, or plan response order."
always: false
requires: {}
---

# Inbox Triage

## Quick Workflow

1. Group inbox items by topic and sender intent.
2. Classify each item into exactly one bucket.
3. Add one next action per actionable item.
4. Surface blockers and hard deadlines first.

## Output Format

- `urgent today`: must be handled today
- `this week`: important but not same-day urgent
- `later`: deferrable items
- `archive`: no action needed

Each listed item should include a one-line `next action`.

## Edge Cases

- If the inbox is very large, triage newest 50 first and state that scope.
- If urgency is unclear, default to `this week` with a confidence note.
- If two items conflict, flag conflict explicitly instead of guessing.
