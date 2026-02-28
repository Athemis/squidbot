---
name: personal-ops-router
description: "Routes multi-step personal productivity requests to the most suitable skills and returns a unified result. Use when the user asks to coordinate planning, research, reminders, and follow-up in one workflow."
always: false
requires: {}
---

# Personal Ops Router

## Quick Workflow

1. Classify the user request into sub-problems.
2. Route each part to the best matching skill.
3. Merge results into one prioritized execution plan.
4. Surface dependencies, deadlines, and next actions.

Preferred routing targets:
- `research` for fact-finding
- `summarize` for compression
- `cron` for reminders/scheduling
- `memory` for durable preferences
- productivity skills for triage, extraction, and reviews

## Output Format

- `selected_skill`: chosen skill per sub-problem
- `execution_plan`: ordered steps with rationale
- `result_summary`: concise final synthesis

## Edge Cases

- If routing confidence is low, present top 2 routing options with rationale.
- If tools are missing for a route, provide a fallback manual plan.
- If request is actually single-skill, skip orchestration and call that skill directly.
