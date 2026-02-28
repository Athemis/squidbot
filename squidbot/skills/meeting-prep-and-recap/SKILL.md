---
name: meeting-prep-and-recap
description: "Prepares meetings with focused agendas and captures post-meeting outcomes. Use when the user asks to plan a meeting, align participants, or generate a recap with action items."
always: false
requires: {}
---

# Meeting Prep and Recap

## Quick Workflow

1. Prep phase: define objective, participants, and agenda order.
2. During/after phase: capture decisions, action items, and owners.
3. Publish recap with clear deadlines and next check-in.

## Output Format

- `prep`: objective, participants, agenda
- `recap`: key points and decisions
- `actions`: task, owner, due date

## Edge Cases

- If objective is vague, ask for one concrete outcome first.
- If decisions are unresolved, mark as pending instead of inferring.
- If ownership is missing, assign `owner: unknown` and flag for follow-up.
