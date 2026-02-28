---
name: follow-up-manager
description: "Tracks open loops and prepares follow-up actions with explicit reminder timing. Use when the user asks to chase pending replies, commitments, or unresolved threads."
always: false
requires: {}
---

# Follow-up Manager

## Quick Workflow

1. Identify unresolved commitments and waiting states.
2. Draft a concise follow-up message for each target.
3. Propose a reminder time based on urgency.
4. When timing is confirmed, schedule reminder with `cron_add`.

## Output Format

- `follow_up_target`: person, team, or thread
- `status`: what is waiting
- `message_draft`: short follow-up text
- `remind_at`: concrete time or `unspecified`

## Edge Cases

- If timing is missing, ask for timing before calling `cron_add`.
- If the user asks for one-time reminders only, still use `cron_add` with a one-off schedule.
- If follow-up would be duplicate/noisy, recommend waiting and explain why.
