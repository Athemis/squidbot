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

```
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
