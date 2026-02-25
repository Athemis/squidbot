# Draft: Structured GitHub Issue Workflow (Athemis/squidbot)

## Requirements (confirmed)
- "Ich moechte die Issues auf github strukturiert abarbeiten."

## Technical Decisions
- Use GitHub Projects v2 as the workflow surface (single source of truth for status/priority/size/area).
- Use a minimal label taxonomy (labels only for `type:*`; no status/priority labels).
- Use a weekly triage cadence (10-15 minutes).

## Research Findings
- Repo: https://github.com/Athemis/squidbot (default branch: main)
- GitHub CLI: authenticated as `Athemis`
- Open issues (currently 4): #2, #4, #5, #6
- All current open issues are `memory`-related (core refactor/chore/fix + one longer-term idea)
- Existing labels: only GitHub defaults (bug, enhancement, documentation, ...); no repo-specific labels
- No `.github/` directory in the repo (no issue templates / workflow automation present)
- No open milestones
- No GitHub Projects found for the repo

## Open Questions
- None blocking (workflow surface / granularity / cadence confirmed).

## Scope Boundaries
- INCLUDE: label taxonomy, triage rules, prioritization, definition of "ready", mapping issues->branches/PRs, lightweight automation suggestions.
- EXCLUDE: implementing the fixes/features inside the issues themselves.
