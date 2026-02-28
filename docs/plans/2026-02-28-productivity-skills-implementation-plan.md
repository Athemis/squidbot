# Productivity Skills Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a first productivity skill pack for squidbot with 8 focused skills that improve daily planning, inbox handling, follow-ups, and review workflows.

**Architecture:** Implement pure skill-content additions under `squidbot/skills/` with compact `SKILL.md` files. Wave 1 ships high-impact daily workflows first, then Wave 2 adds strategic review/orchestration skills. Keep all skills spec-aligned (`name`, `description` with what+when triggers) and concise.

**Tech Stack:** Markdown, YAML frontmatter, existing squidbot skills loader

---

### Task 1: Create Wave 1 skill directories and baseline SKILL.md files

**Files:**
- Create: `squidbot/skills/task-extractor/SKILL.md`
- Create: `squidbot/skills/inbox-triage/SKILL.md`
- Create: `squidbot/skills/follow-up-manager/SKILL.md`
- Create: `squidbot/skills/daily-briefing/SKILL.md`

**Step 1: Create four skill directories**

Run: `mkdir -p squidbot/skills/task-extractor squidbot/skills/inbox-triage squidbot/skills/follow-up-manager squidbot/skills/daily-briefing`
Expected: Directories exist under `squidbot/skills/`

**Step 2: Write `task-extractor/SKILL.md`**

Include:
- Frontmatter:
  - `name: task-extractor`
  - `description` with what+when trigger
  - `always: false`
  - `requires: {}`
- Sections:
  - `# Task Extractor`
  - `## Quick Workflow`
  - `## Output Format`
  - `## Edge Cases`

**Step 3: Write `inbox-triage/SKILL.md`**

Include:
- Trigger-focused description for inbox backlog triage
- Deterministic category output (`urgent today`, `this week`, `later`, `archive`)

**Step 4: Write `follow-up-manager/SKILL.md`**

Include:
- Trigger-focused description for open loops
- Explicit use of `cron_add` for reminders when timing is specified

**Step 5: Write `daily-briefing/SKILL.md`**

Include:
- Trigger-focused description for morning/start-of-day requests
- Output sections: `top 3`, schedule, follow-ups, risks

**Step 6: Verify frontmatter and naming for Wave 1 skills**

Run:

```bash
python - <<'PY'
from pathlib import Path
import re

skills = [
    Path('squidbot/skills/task-extractor/SKILL.md'),
    Path('squidbot/skills/inbox-triage/SKILL.md'),
    Path('squidbot/skills/follow-up-manager/SKILL.md'),
    Path('squidbot/skills/daily-briefing/SKILL.md'),
]
name_re = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$')
for path in skills:
    text = path.read_text(encoding='utf-8')
    assert text.startswith('---\n'), f'missing frontmatter: {path}'
    end = text.find('\n---\n', 4)
    assert end != -1, f'unterminated frontmatter: {path}'
    fm = text[4:end]
    fields = {}
    for line in fm.splitlines():
        if ':' in line:
            key, val = line.split(':', 1)
            fields[key.strip()] = val.strip().strip('"')
    name = fields.get('name', '')
    desc = fields.get('description', '')
    assert name_re.match(name), f'invalid name: {name} ({path})'
    assert desc and len(desc) <= 1024 and 'Use when' in desc, f'bad description: {path}'
print('wave1 metadata OK')
PY
```

Expected: `wave1 metadata OK`

**Step 7: Commit Wave 1**

```bash
git add squidbot/skills/task-extractor/SKILL.md squidbot/skills/inbox-triage/SKILL.md squidbot/skills/follow-up-manager/SKILL.md squidbot/skills/daily-briefing/SKILL.md
git commit -m "feat(skills): add wave 1 productivity skills"
```

---

### Task 2: Create Wave 2 skill directories and SKILL.md files

**Files:**
- Create: `squidbot/skills/weekly-review/SKILL.md`
- Create: `squidbot/skills/meeting-prep-and-recap/SKILL.md`
- Create: `squidbot/skills/decision-log/SKILL.md`
- Create: `squidbot/skills/personal-ops-router/SKILL.md`

**Step 1: Create four skill directories**

Run: `mkdir -p squidbot/skills/weekly-review squidbot/skills/meeting-prep-and-recap squidbot/skills/decision-log squidbot/skills/personal-ops-router`
Expected: Directories exist under `squidbot/skills/`

**Step 2: Write `weekly-review/SKILL.md`**

Include:
- Trigger wording for end-of-week reflection
- Output schema for wins, unfinished, lessons, next-week priorities

**Step 3: Write `meeting-prep-and-recap/SKILL.md`**

Include:
- Trigger wording for pre-meeting and post-meeting workflows
- Two-phase structure (`prep` and `recap`)

**Step 4: Write `decision-log/SKILL.md`**

Include:
- Trigger wording for decision capture
- Structured template for context, options, rationale, follow-up actions

**Step 5: Write `personal-ops-router/SKILL.md`**

Include:
- Trigger wording for multi-step orchestration requests
- Routing guidance to existing skills (`research`, `summarize`, `cron`, `memory`) and new productivity skills

**Step 6: Verify frontmatter and naming for Wave 2 skills**

Run the same metadata script from Task 1 with Wave 2 file paths.
Expected: `wave2 metadata OK`

**Step 7: Commit Wave 2**

```bash
git add squidbot/skills/weekly-review/SKILL.md squidbot/skills/meeting-prep-and-recap/SKILL.md squidbot/skills/decision-log/SKILL.md squidbot/skills/personal-ops-router/SKILL.md
git commit -m "feat(skills): add wave 2 productivity skills"
```

---

### Task 3: Consistency pass across all productivity skills

**Files:**
- Modify: `squidbot/skills/task-extractor/SKILL.md`
- Modify: `squidbot/skills/inbox-triage/SKILL.md`
- Modify: `squidbot/skills/follow-up-manager/SKILL.md`
- Modify: `squidbot/skills/daily-briefing/SKILL.md`
- Modify: `squidbot/skills/weekly-review/SKILL.md`
- Modify: `squidbot/skills/meeting-prep-and-recap/SKILL.md`
- Modify: `squidbot/skills/decision-log/SKILL.md`
- Modify: `squidbot/skills/personal-ops-router/SKILL.md`

**Step 1: Normalize section structure**

Each skill should include, in this order where applicable:
1. Title (`# ...`)
2. `## Quick Workflow`
3. `## Output Format`
4. `## Edge Cases`

**Step 2: Keep concise length**

Run:

```bash
python - <<'PY'
from pathlib import Path

paths = list(Path('squidbot/skills').glob('*/SKILL.md'))
for p in sorted(paths):
    lines = p.read_text(encoding='utf-8').splitlines()
    assert len(lines) < 500, f'too long: {p} ({len(lines)} lines)'
print('all skills <500 lines')
PY
```

Expected: `all skills <500 lines`

**Step 3: Commit consistency updates**

```bash
git add squidbot/skills/*/SKILL.md
git commit -m "docs(skills): align productivity skill structure and style"
```

---

### Task 4: Documentation update for expanded skill inventory

**Files:**
- Modify: `docs/plans/2026-02-21-squidbot-design.md`

**Step 1: Update bundled skills inventory snippet**

Add the 8 new skill names in the bundled skill list section.

**Step 2: Verify no stale references**

Run: `rg "task-extractor|inbox-triage|follow-up-manager|daily-briefing|weekly-review|meeting-prep-and-recap|decision-log|personal-ops-router" docs/plans/2026-02-21-squidbot-design.md`
Expected: all names found in inventory section

**Step 3: Commit doc update**

```bash
git add docs/plans/2026-02-21-squidbot-design.md
git commit -m "docs: refresh bundled skill inventory with productivity skills"
```

---

### Task 5: Final verification

**Step 1: Lint**

Run: `uv run ruff check .`
Expected: no issues

**Step 2: Format check**

Run: `uv run ruff format . --check`
Expected: no reformat needed

**Step 3: Tests**

Run: `uv run pytest`
Expected: all tests pass

**Step 4: Final commit if needed**

If verification changes files:

```bash
git add .
git commit -m "chore: finalize productivity skills rollout"
```

If no files changed, skip this step.
