---
name: cron
description: "Schedules recurring reminders and tasks with cron expressions or `every N` intervals. Use when the user asks to run something on a repeating schedule."
always: false
requires: {}
---

# Cron Skill

Use `squidbot cron add` to schedule recurring tasks. Supports standard cron expressions (for
example `0 9 * * 1-5`) and interval syntax (`every 3600`).

## When to Use

- The user asks for recurring reminders.
- A task should run at specific times or days.
- A recurring background prompt should be automated.

## Quick Workflow

1. Convert the request into cron syntax or `every N` interval syntax.
2. Add the job with `squidbot cron add --schedule "..." --prompt "..."`.
3. Confirm the job with `squidbot cron list`.
4. Edit or remove the job with `squidbot cron remove <id>` when requested.

## Examples

```bash
# Weekdays at 09:00
squidbot cron add --schedule "0 9 * * 1-5" --prompt "Send daily standup reminder"

# Every hour
squidbot cron add --schedule "every 3600" --prompt "Check inbox backlog"
```
