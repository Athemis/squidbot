# Placeholder Skills Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace placeholder content in 4 SKILL.md files with compact, actionable LLM instructions.

**Architecture:** Pure markdown updates to skill files. No code changes. Skills reference existing tools (shell, web_search, fetch_url) and follow project conventions from AGENTS.md.

**Tech Stack:** Markdown, YAML frontmatter

---

### Task 1: Update git Skill

**Files:**
- Modify: `squidbot/skills/git/SKILL.md`

**Step 1: Replace git/SKILL.md content**

Write the following content to `squidbot/skills/git/SKILL.md`:

````markdown
---
name: git
description: "Local git workflows: commits, branches, merges, conflict resolution."
always: false
requires:
  bins:
    - git
---

# Git Skill

Use the `shell` tool to execute git commands for local version control operations.

## When to Use

- Creating commits, branches, tags
- Merging branches, resolving conflicts
- Viewing history, diffs, blame
- Local repository operations

## When NOT to Use

- GitHub-specific operations (PRs, issues, CI) → use `github` skill
- Cloning from GitHub → use `git clone` directly, then the `github` skill for remote ops

## Branch Naming

Follow Conventional Commits prefixes:

| Prefix | Purpose |
|--------|---------|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `refactor/` | Code refactoring |
| `docs/` | Documentation |
| `test/` | Test additions/changes |
| `chore/` | Maintenance tasks |

Example: `feat/add-email-channel`, `fix/memory-leak`

## Commit Messages

Format: `type(scope): description`

````text
feat(email): add IMAP connection pooling
fix(agent): handle empty tool responses
docs(readme): update installation steps
```

Keep the first line under 72 characters. Add body if context is needed.

## Common Operations

### Branching

```bash
git checkout -b feat/new-feature main
```

### Committing

```bash
git add -p  # Stage interactively
git commit -m "feat(core): add new capability"
```

### Merging

```bash
git checkout main
git merge feat/new-feature
```

### Conflict Resolution

1. Run `git status` to see conflicting files
2. Open each file and look for `<<<<<<<` markers
3. Edit to resolve (choose/combine changes)
4. Stage resolved files: `git add <file>`
5. Complete merge: `git commit`

## Project Conventions

See AGENTS.md for:
- GPG signing requirements
- Branch workflow (feature branches → PR → main)
- Conventional Commits format
```

**Step 2: Verify file syntax**

Run: `cat squidbot/skills/git/SKILL.md | head -20`
Expected: YAML frontmatter followed by markdown content

**Step 3: Commit**

```bash
git add squidbot/skills/git/SKILL.md
git commit -m "feat(skills): implement git skill"
```

---

### Task 2: Update github Skill

**Files:**
- Modify: `squidbot/skills/github/SKILL.md`

**Step 1: Replace github/SKILL.md content**

Write the following content to `squidbot/skills/github/SKILL.md`:

````markdown
---
name: github
description: "GitHub via `gh` CLI: issues, PRs, CI runs, reviews. Requires `gh auth login`."
always: false
requires:
  bins:
    - gh
---

# GitHub Skill

Use the `shell` tool to execute `gh` CLI commands for GitHub operations.

## When to Use

- Viewing/creating pull requests
- Managing issues
- Checking CI/workflow runs
- GitHub API queries

## When NOT to Use

- Local git operations → use `git` skill
- Non-GitHub remotes → use appropriate CLI

## Setup

```bash
gh auth login
gh auth status
````

## Pull Requests

```bash
# List PRs
gh pr list --repo owner/repo

# View PR details
gh pr view 55 --repo owner/repo

# Create PR
gh pr create --title "feat: add feature" --body "Description"

# Check CI status
gh pr checks 55 --repo owner/repo

# Merge
gh pr merge 55 --squash --repo owner/repo
```

## Issues

```bash
# List open issues
gh issue list --repo owner/repo --state open

# Create issue
gh issue create --title "Bug: description" --body "Details"

# Close issue
gh issue close 42 --repo owner/repo
```

## CI/Workflows

```bash
# List recent runs
gh run list --repo owner/repo --limit 10

# View specific run
gh run view <run-id> --repo owner/repo

# View failed logs
gh run view <run-id> --repo owner/repo --log-failed
```

## JSON Output

Use `--json` with `--jq` for structured output:

```bash
gh pr list --json number,title,state --jq '.[] | "\(.number): \(.title)"'
```

## Tips

- Use full URLs: `gh pr view https://github.com/owner/repo/pull/55`
- Specify `--repo owner/repo` when not in a git directory
- Use `gh api` for advanced queries
```

**Step 2: Verify file syntax**

Run: `cat squidbot/skills/github/SKILL.md | head -20`
Expected: YAML frontmatter followed by markdown content

**Step 3: Commit**

```bash
git add squidbot/skills/github/SKILL.md
git commit -m "feat(skills): implement github skill"
```

---

### Task 3: Update research Skill

**Files:**
- Modify: `squidbot/skills/research/SKILL.md`

**Step 1: Replace research/SKILL.md content**

Write the following content to `squidbot/skills/research/SKILL.md`:

````markdown
---
name: research
description: "Structured research workflow using web_search and fetch_url tools."
always: false
requires: {}
---

# Research Skill

Conduct structured research using the `web_search` and `fetch_url` tools.

## Workflow

### 1. Define Query

Clarify what information is needed. Break complex questions into sub-queries.

### 2. Search

Use `web_search` to find relevant sources:

````
web_search(query="topic", num_results=10)
```

### 3. Evaluate Sources

Before trusting a source:
- Check domain credibility (.edu, .gov, established publications)
- Look for publication date (is it current?)
- Cross-reference claims with other sources

Use `fetch_url` to read full content before citing.

### 4. Extract Information

- Pull key facts, not entire articles
- Note source URLs for citation
- Flag conflicting information

### 5. Synthesize

Present findings as:
1. **Summary** — 2-3 sentence overview
2. **Key Points** — bullet list of main findings
3. **Sources** — URLs with brief descriptions

## Best Practices

- **Triangulate**: Confirm facts across 2-3 independent sources
- **Cite**: Always include source URLs
- **Date check**: Note when information was published
- **Scope**: Stay focused on the original question

## Example Output

```
## Summary
[Topic] refers to...

## Key Points
- Point 1 (Source: url1.com)
- Point 2 (Source: url2.com)
- Point 3 (Source: url1.com, url3.com)

## Sources
- url1.com — Description
- url2.com — Description
```
```

**Step 2: Verify file syntax**

Run: `cat squidbot/skills/research/SKILL.md | head -20`
Expected: YAML frontmatter followed by markdown content

**Step 3: Commit**

```bash
git add squidbot/skills/research/SKILL.md
git commit -m "feat(skills): implement research skill"
```

---

### Task 4: Update summarize Skill

**Files:**
- Modify: `squidbot/skills/summarize/SKILL.md`

**Step 1: Replace summarize/SKILL.md content**

Write the following content to `squidbot/skills/summarize/SKILL.md`:

````markdown
---
name: summarize
description: "Summarize documents, conversations, or content into key points."
always: false
requires: {}
---

# Summarize Skill

Condense long-form content into structured, actionable summaries.

## When to Use

- Long documents, articles, reports
- Meeting transcripts, chat logs
- Email threads
- Any content needing distillation

## Output Structure

### 1. Key Points (Required)

Bullet list of the most important takeaways (3-7 items).

### 2. Details (Optional)

Supporting context for key points, if needed.

### 3. Action Items (If Applicable)

Next steps, decisions, or follow-ups.

## Guidelines

- **Length**: Target ~10% of original content
- **Format**: Bullet points, not prose
- **Language**: Match the input language
- **Focus**: What matters most to the reader

## Example

**Input:** 2000-word article about microservices

**Output:**

```
## Key Points
- Microservices improve scalability but add complexity
- Start with monolith, extract services when needed
- Each service should own its data
- Use API gateways for cross-cutting concerns

## Details
- Deployment: Each service deploys independently
- Communication: Prefer async messaging over sync HTTP
- Monitoring: Distributed tracing is essential

## Action Items
- Assess team DevOps readiness before migration
- Define data consistency strategy per service boundary
- Budget for latency/observability in service-to-service calls
````
```

**Step 2: Verify file syntax**

Run: `cat squidbot/skills/summarize/SKILL.md | head -20`
Expected: YAML frontmatter followed by markdown content

**Step 3: Commit**

```bash
git add squidbot/skills/summarize/SKILL.md
git commit -m "feat(skills): implement summarize skill"
```

---

### Task 5: Final Verification

**Step 1: Run linting**

Run: `uv run ruff check .`
Expected: No errors

**Step 2: Run tests**

Run: `uv run pytest`
Expected: All tests pass

**Step 3: Verify all skills updated**

Run: `grep -L "coming soon" squidbot/skills/{git,github,research,summarize}/SKILL.md`
Expected: All 4 files listed

---

## Summary

| Task | File | Action |
|------|------|--------|
| 1 | `squidbot/skills/git/SKILL.md` | Replace content |
| 2 | `squidbot/skills/github/SKILL.md` | Replace content |
| 3 | `squidbot/skills/research/SKILL.md` | Replace content |
| 4 | `squidbot/skills/summarize/SKILL.md` | Replace content |
| 5 | - | Verify and test |
