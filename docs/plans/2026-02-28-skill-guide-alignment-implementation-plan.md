# Skill Guide Alignment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Align all bundled skills with Claude skill best-practice guidance by improving discoverability metadata and concise workflow structure.

**Architecture:** This is a content-only pass over existing `SKILL.md` files. No tool/runtime behavior changes are made. The update standardizes frontmatter descriptions and adds compact, actionable usage/workflow sections where currently missing.

**Tech Stack:** Markdown, YAML frontmatter

---

### Task 1: Standardize discovery descriptions

**Files:**
- Modify: `squidbot/skills/cron/SKILL.md`
- Modify: `squidbot/skills/git/SKILL.md`
- Modify: `squidbot/skills/github/SKILL.md`
- Modify: `squidbot/skills/memory/SKILL.md`
- Modify: `squidbot/skills/research/SKILL.md`
- Modify: `squidbot/skills/skill-creator/SKILL.md`
- Modify: `squidbot/skills/summarize/SKILL.md`

**Step 1: Update `description` in each frontmatter**

Apply this pattern to every skill description:
- First clause: what the skill does.
- Second clause: when to use it (trigger phrase: "Use when ...").
- Third person wording, no "I" or "you".

Example target style:

```yaml
description: "Manages local git workflows including branches, commits, and merges. Use when the task involves local repository history, staging, commit creation, or conflict resolution."
```

**Step 2: Verify metadata validity**

Run:

```bash
python - <<'PY'
from pathlib import Path
import re

name_re = re.compile(r'^[a-z0-9-]{1,64}$')
for skill in sorted(Path('squidbot/skills').glob('*/SKILL.md')):
    text = skill.read_text(encoding='utf-8')
    assert text.startswith('---\n'), f"missing frontmatter: {skill}"
    end = text.find('\n---\n', 4)
    assert end != -1, f"unterminated frontmatter: {skill}"
    fm = text[4:end].splitlines()
    fields = {line.split(':', 1)[0].strip(): line.split(':', 1)[1].strip() for line in fm if ':' in line}
    name = fields.get('name', '').strip('"')
    desc = fields.get('description', '').strip('"')
    assert name_re.match(name), f"invalid name: {skill} -> {name}"
    assert desc, f"empty description: {skill}"
print('metadata OK')
PY
```

Expected: `metadata OK`

**Step 3: Commit**

```bash
git add squidbot/skills/*/SKILL.md
git commit -m "docs(skills): improve skill descriptions for discovery"
```

---

### Task 2: Add compact usage/workflow structure where thin

**Files:**
- Modify: `squidbot/skills/cron/SKILL.md`
- Modify: `squidbot/skills/skill-creator/SKILL.md`

**Step 1: Expand `cron` with concise operational structure**

Add compact sections:
- `When to Use`
- `Quick Workflow` (3-5 steps)
- `Examples` with one cron expression and one `every N` example

Use deterministic defaults, for example:

```markdown
## Quick Workflow
1. Convert the request into either cron or `every N` syntax.
2. Add the job with `squidbot cron add --schedule "..." --prompt "..."`.
3. Confirm with `squidbot cron list`.
```

**Step 2: Expand `skill-creator` with concise authoring workflow**

Add compact sections:
- `When to Use`
- `Workflow` (create directory, write frontmatter, add body, validate)
- `Validation` checklist

Include one canonical frontmatter snippet:

```yaml
---
name: example-skill
description: "Performs X. Use when Y."
always: false
requires: {}
---
```

**Step 3: Commit**

```bash
git add squidbot/skills/cron/SKILL.md squidbot/skills/skill-creator/SKILL.md
git commit -m "docs(skills): add concise workflows to cron and skill-creator"
```

---

### Task 3: Consistency pass across all skills

**Files:**
- Modify: `squidbot/skills/git/SKILL.md`
- Modify: `squidbot/skills/github/SKILL.md`
- Modify: `squidbot/skills/memory/SKILL.md`
- Modify: `squidbot/skills/research/SKILL.md`
- Modify: `squidbot/skills/summarize/SKILL.md`

**Step 1: Normalize terminology and section labels**

Enforce:
- `GitHub` casing
- Tool names in monospace where referenced
- Stable headers such as `When to Use`, `Workflow`, `Tips` (where relevant)

**Step 2: Keep brevity constraints**

Run:

```bash
python - <<'PY'
from pathlib import Path

for skill in sorted(Path('squidbot/skills').glob('*/SKILL.md')):
    lines = skill.read_text(encoding='utf-8').splitlines()
    # conservative bound for whole file; guide requirement is body < 500
    assert len(lines) < 550, f"too long: {skill} ({len(lines)} lines)"
print('length check OK')
PY
```

Expected: `length check OK`

**Step 3: Commit**

```bash
git add squidbot/skills/git/SKILL.md squidbot/skills/github/SKILL.md squidbot/skills/memory/SKILL.md squidbot/skills/research/SKILL.md squidbot/skills/summarize/SKILL.md
git commit -m "docs(skills): align terminology and structure across skill set"
```

---

### Task 4: Project-level verification

**Step 1: Run linting**

Run: `uv run ruff check .`
Expected: no issues

**Step 2: Run formatting check**

Run: `uv run ruff format . --check`
Expected: no changes needed

**Step 3: Run tests**

Run: `uv run pytest`
Expected: all tests pass

**Step 4: Commit any final doc touch-ups**

```bash
git add .
git commit -m "docs(skills): finalize best-practice alignment pass"
```

If no additional changes exist, skip this commit.
