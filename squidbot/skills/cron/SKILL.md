---
name: cron
description: "Schedules recurring reminders and tasks with cron expressions or `every N` intervals. Use when the user asks to run something on a repeating schedule."
always: false
requires: {}
---

# Cron Skill

Use cron tools to manage recurring tasks. Supports standard cron expressions (for example
`0 9 * * 1-5`) and interval syntax (`every 3600`).

## Tools

- `cron_add`: create a job (`name`, `message`, `schedule`, optional `timezone`, `channel`,
  `enabled`)
- `cron_list`: list configured jobs
- `cron_remove`: remove a job by `job_id`
- `cron_set_enabled`: enable/disable a job by `job_id`

## When to Use

- The user asks for recurring reminders.
- A task should run at specific times or days.
- A recurring background prompt should be automated.

## Quick Workflow

1. Convert the request into cron syntax or `every N` interval syntax.
2. Create the job with `cron_add`.
3. Confirm creation with `cron_list`.
4. If needed, disable with `cron_set_enabled` or delete with `cron_remove`.

## Examples

```text
# Weekdays at 09:00
cron_add(name="daily-standup", message="Send daily standup reminder", schedule="0 9 * * 1-5")

# Every hour
cron_add(name="inbox-backlog", message="Check inbox backlog", schedule="every 3600")

# Disable a job
cron_set_enabled(job_id="<job-id>", enabled=false)

# Remove a job
cron_remove(job_id="<job-id>")
```
