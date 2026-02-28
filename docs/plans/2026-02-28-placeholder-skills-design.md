# Placeholder Skills Design

**Date:** 2026-02-28
**Status:** Approved
**Scope:** git, github, research, summarize

## Overview

Replace placeholder content in 4 bundled skills with compact, squidbot-native LLM instructions.
Skills are pure prompts/guides — they reference existing tools but do not define new ones.

## Skills

### 1. git

**Purpose:** Local git workflows: commits, branches, merges, conflict resolution.

**Frontmatter:**
```yaml
name: git
description: "Local git workflows: commits, branches, merges, conflict resolution."
always: false
requires: { bins: ["git"] }
```

**Content Sections:**
- When to use vs. github skill
- Branch naming conventions (feat/, fix/, refactor/)
- Commit message format (Conventional Commits)
- Merge conflict resolution workflow
- Reference to AGENTS.md for project-specific rules

### 2. github

**Purpose:** GitHub operations via `gh` CLI: issues, PRs, CI runs, reviews.

**Frontmatter:**
```yaml
name: github
description: "GitHub via `gh` CLI: issues, PRs, CI runs, reviews. Requires `gh auth login`."
always: false
requires: { bins: ["gh"] }
```

**Content Sections:**
- When to use vs. git skill
- Auth verification
- PR workflow (list, view, create, merge)
- Issue management
- CI/run monitoring
- JSON output with --jq

### 3. research

**Purpose:** Structured research workflow using web_search and fetch_url tools.

**Frontmatter:**
```yaml
name: research
description: "Structured research workflow using web_search and fetch_url tools."
always: false
requires: {}
```

**Content Sections:**
- 5-phase workflow: Query → Search → Evaluate → Extract → Synthesize
- Source triangulation
- URL evaluation before trust
- Citation requirements
- Reference to web_search and fetch_url tools

### 4. summarize

**Purpose:** Summarize documents, conversations, or content into key points.

**Frontmatter:**
```yaml
name: summarize
description: "Summarize documents, conversations, or content into key points."
always: false
requires: {}
```

**Content Sections:**
- When to use (long documents, meetings, chats)
- Output structure: Key Points → Details → Action Items
- Formatting: bullet points, not prose
- Length target: ~10% of original
- Language: match input language

## Style Guidelines

- **Length:** ~50-100 lines per skill (compact)
- **Format:** Markdown with code blocks for commands
- **Tone:** Direct, actionable, no fluff
- **Language:** English (project default)
- **References:** Link to AGENTS.md and existing tools where relevant

## Files to Modify

| File | Action |
|------|--------|
| `squidbot/skills/git/SKILL.md` | Replace placeholder content |
| `squidbot/skills/github/SKILL.md` | Replace placeholder content |
| `squidbot/skills/research/SKILL.md` | Replace placeholder content |
| `squidbot/skills/summarize/SKILL.md` | Replace placeholder content |

## Testing

No code changes — skills are pure markdown. Verification:
1. `uv run ruff check .` passes
2. `uv run pytest` passes (existing tests unaffected)
3. Manual inspection of SKILL.md files

## References

- OpenClaw github skill: <https://raw.githubusercontent.com/openclaw/openclaw/refs/heads/main/skills/github/SKILL.md>
- OpenClaw summarize skill: <https://raw.githubusercontent.com/openclaw/openclaw/refs/heads/main/skills/summarize/SKILL.md>
- AGENTS.md for project conventions
