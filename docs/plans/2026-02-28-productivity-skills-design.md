# Design: Productivity Skill Expansion

## Date

2026-02-28

## Status

Approved

## Goal

Define a productivity-focused skill expansion roadmap for squidbot, prioritizing daily personal
assistant workflows with high practical impact.

## Context

Current bundled skills cover core foundations (`memory`, `research`, `summarize`, `cron`,
`git`, `github`, `skill-creator`) but do not yet provide dedicated operating modes for daily
personal productivity workflows (triage, planning, follow-up, and recurring review loops).

External inspiration sources reviewed:
- OpenClaw official skills catalog (GitHub API listing)
- ClawHub repository and CLI docs
- Selected OpenClaw skill implementations (`clawhub`, `gh-issues`, `skill-creator`)

## Priority Category

Productivity-first.

## Approaches Considered

### A. Workflow-first (selected)

Add skills mapped to recurring daily workflows (inbox triage, task extraction, follow-up, daily
briefing, weekly review, meeting prep/recap).

Pros:
- Fastest user-visible value
- Fits squidbot primary use case (personal assistant)
- Reuses existing tooling (`cron`, `memory`, `research`, `summarize`)

Cons:
- Requires strong output templates to avoid overlap between skills

### B. Channel-first

Prioritize channel-specific operations (email/matrix handling and moderation patterns).

Pros:
- Strong adapter alignment

Cons:
- Lower immediate productivity impact for day planning

### C. Domain-pack-first

Create larger thematic bundles before shipping individual workflow skills.

Pros:
- Clean packaging

Cons:
- Slower time-to-value

## Selected Roadmap (Two Waves)

### Wave 1 (highest impact, lowest complexity)

1. `task-extractor`
2. `inbox-triage`
3. `follow-up-manager`
4. `daily-briefing`

### Wave 2 (strategic layer)

5. `weekly-review`
6. `meeting-prep-and-recap`
7. `decision-log`
8. `personal-ops-router`

Rationale:
- Wave 1 reduces daily operational load immediately.
- Wave 2 introduces reflection, documentation quality, and orchestration.

## Proposed Skills (Spec-Level)

All skills will follow Agent Skills spec and Claude best-practices guidance:
- `description` contains what the skill does + when to use it
- concise body with default workflow
- compact structure (`Quick Workflow`, `Output Format`, `Edge Cases`)

### 1. `task-extractor`

Purpose:
- Extract actionable tasks from unstructured messages.

Trigger pattern:
- "extract tasks", "turn this thread into TODOs", "what are the action items"

Output shape:
- `task`, `owner`, `due`, `priority`, `source`

### 2. `inbox-triage`

Purpose:
- Prioritize inbox items by urgency, effort, and relevance.

Trigger pattern:
- "triage my inbox", "what is urgent", "help clear backlog"

Output shape:
- `urgent today`, `this week`, `later`, `archive`

### 3. `follow-up-manager`

Purpose:
- Detect open loops and schedule follow-ups.

Trigger pattern:
- "follow up", "remind me to ping", "what is still waiting"

Output shape:
- `follow_up_target`, `message_draft`, `remind_at`

### 4. `daily-briefing`

Purpose:
- Generate a compact daily overview and top priorities.

Trigger pattern:
- "morning brief", "what is on deck today"

Output shape:
- `top 3`, `today schedule`, `follow-ups`, `risks`

### 5. `weekly-review`

Purpose:
- Summarize weekly progress and define next-week priorities.

Trigger pattern:
- "weekly review", "what did I complete this week"

Output shape:
- `wins`, `unfinished`, `lessons`, `next week priorities`

### 6. `meeting-prep-and-recap`

Purpose:
- Create meeting agendas and post-meeting recaps.

Trigger pattern:
- "prepare meeting agenda", "summarize this meeting"

Output shape:
- `agenda`, `decision log`, `actions`

### 7. `decision-log`

Purpose:
- Document decisions, trade-offs, and follow-up actions.

Trigger pattern:
- "record this decision", "capture rationale"

Output shape:
- `decision`, `context`, `options`, `rationale`, `actions`

### 8. `personal-ops-router`

Purpose:
- Route multi-step productivity requests to the best matching skills.

Trigger pattern:
- "organize my day", "coordinate this for me"

Output shape:
- `selected_skill`, `execution_plan`, `result_summary`

## Boundaries and Non-Goals

- No new tool adapters are required for initial versions.
- Skills should orchestrate existing capabilities first.
- Avoid large reference trees until real usage reveals gaps.

## Risks and Mitigations

- Overlap between skills:
  - Mitigation: strict trigger descriptions and fixed output schemas.
- Prompt bloat:
  - Mitigation: keep each `SKILL.md` concise; use progressive disclosure only when needed.
- Premature complexity:
  - Mitigation: ship Wave 1 first, validate with usage, then expand.

## Validation Strategy

- Spec checks:
  - valid frontmatter (`name`, `description`), naming constraints, concise descriptions
- Consistency checks:
  - trigger-based descriptions, predictable output structure, shared terminology
- Repo checks before commit:
  - `uv run ruff check .`
  - `uv run ruff format . --check`
  - `uv run pytest`
