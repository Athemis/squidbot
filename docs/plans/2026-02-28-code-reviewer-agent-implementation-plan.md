# Code Reviewer Agent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a repo-specific strict Python code-review agent that works as both primary and subagent with read-only source access and a constrained verification-command whitelist.

**Architecture:** Define one agent markdown file under `.opencode/agent/` with YAML frontmatter for mode/tools/permissions plus a focused system prompt aligned to `AGENTS.md`. Validation uses only allowed commands and static checks to confirm discoverability and behavior expectations.

**Tech Stack:** OpenCode agent markdown config, YAML frontmatter, repository standards from `AGENTS.md`, validation commands via `uv`.

---

### Task 1: Create agent file scaffold

**Files:**
- Create: `.opencode/agent/code-reviewer.md`
- Reference: `AGENTS.md`

**Step 1: Create directory structure**

Create `.opencode/agent/` if it does not exist.

**Step 2: Write initial agent frontmatter**

Use this exact scaffold:

```markdown
---
description: Strict Python code reviewer for squidbot repository standards
mode: all
temperature: 0.1
tools:
  read: true
  grep: true
  glob: true
  bash: true
  write: false
  edit: false
  webfetch: false
permission:
  write: deny
  edit: deny
  bash:
    "uv run pytest*": allow
    "uv run ruff check .": allow
    "uv run ruff format . --check": allow
    "uv run mypy squidbot/": allow
    "*": deny
---
```

**Step 3: Add placeholder prompt body**

```markdown
# Code Reviewer

You review Python changes for this repository.
```

**Step 4: Verify file exists**

Run: `ls .opencode/agent`
Expected: contains `code-reviewer.md`

**Step 5: Commit**

```bash
git add .opencode/agent/code-reviewer.md
git commit -m "feat(agent): add code-reviewer scaffold"
```

### Task 2: Add strict review rubric and output contract

**Files:**
- Modify: `.opencode/agent/code-reviewer.md`
- Reference: `AGENTS.md`

**Step 1: Write failing behavior checklist (manual)**

Define expected review output requirements before editing:
- Every finding has severity (`critical|major|minor`)
- Every finding has `path:line`
- Findings include impact and fix guidance

Expected (before prompt expansion): requirements are not fully enforced.

**Step 2: Implement full prompt content**

Add sections that instruct the agent to:
- Prioritize correctness/security, then architecture, typing, tests, maintainability
- Enforce repository rules (hexagonal boundaries, strict typing, test expectations)
- Separate `Must Fix` from `Nice to Improve`
- Avoid speculative claims and cite evidence

**Step 3: Validate markdown/frontmatter integrity**

Run: `uv run python -c "import pathlib,sys; p=pathlib.Path('.opencode/agent/code-reviewer.md'); print('ok' if p.exists() and p.read_text().startswith('---') else 'bad')"`
Expected: prints `ok`

**Step 4: Self-review for policy alignment**

Confirm that no instructions permit source editing or unrestricted command execution.

**Step 5: Commit**

```bash
git add .opencode/agent/code-reviewer.md
git commit -m "feat(agent): define strict squidbot code review rubric"
```

### Task 3: Verify behavior and repository compliance

**Files:**
- Verify: `.opencode/agent/code-reviewer.md`
- Verify: `docs/plans/2026-02-28-code-reviewer-agent-design.md`
- Verify: `docs/plans/2026-02-28-code-reviewer-agent-implementation-plan.md`

**Step 1: Run allowed verification commands**

Run each command and capture output:

```bash
uv run ruff check .
uv run ruff format . --check
uv run pytest
uv run mypy squidbot/
```

Expected: command results are recorded; failures are surfaced clearly.

**Step 2: Smoke-check agent invocation paths**

Manual checks:
- Primary selection visibility due to `mode: all`
- Subagent invocation via `@code-reviewer`

Expected: both invocation paths are available.

**Step 3: Final repo status check**

Run: `git status`
Expected: only intended files changed.

**Step 4: Commit**

```bash
git add .opencode/agent/code-reviewer.md docs/plans/2026-02-28-code-reviewer-agent-design.md docs/plans/2026-02-28-code-reviewer-agent-implementation-plan.md
git commit -m "feat(agent): add strict repo-specific code reviewer"
```
