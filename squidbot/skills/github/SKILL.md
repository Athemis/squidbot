---
name: github
description: "Handles GitHub workflows via the `gh` CLI, including pull requests, issues, and CI runs. Use when the task involves GitHub repositories, PRs, issues, or Actions."
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
```

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
