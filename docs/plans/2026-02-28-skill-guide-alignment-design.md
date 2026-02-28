# Design: Align Bundled Skills with Claude Skill Best Practices

## Objective

Align all current bundled skills with the Claude Agent Skills best-practices guide
without adding new skill subfiles. The scope is content quality and discoverability,
not runtime behavior changes.

## Scope

In scope:
- `squidbot/skills/cron/SKILL.md`
- `squidbot/skills/git/SKILL.md`
- `squidbot/skills/github/SKILL.md`
- `squidbot/skills/memory/SKILL.md`
- `squidbot/skills/research/SKILL.md`
- `squidbot/skills/skill-creator/SKILL.md`
- `squidbot/skills/summarize/SKILL.md`

Out of scope:
- Adding new files under skill directories
- Changing tool implementations
- Changing `FsSkillsLoader` behavior

## Approach (Approved)

Use a targeted compliance pass:
- Keep existing skill intent and structure.
- Improve metadata and wording where discovery quality is weak.
- Add lightweight workflow/trigger guidance to short skills.
- Keep each skill concise (<500 lines).

## Design Decisions

### 1. Description quality for discovery

Each `description` should contain both:
- What the skill does
- When it should be used (trigger language)

Descriptions remain in third person and avoid vague text.

### 2. Consistent terminology

Normalize wording across skills:
- `GitHub` casing
- Tool names in monospace where relevant (`web_search`, `fetch_url`, `gh`)
- Stable section naming (`When to Use`, `Workflow`, `Tips`)

### 3. Degrees of freedom

Keep instructions practical and concise:
- Provide one clear default path for common operations
- Keep optional alternatives minimal
- Preserve deterministic instructions where operations are fragile

### 4. Minimal uplift for short skills

`cron` and `skill-creator` currently have very short bodies. Add small structured
sections for usage triggers and basic sequence steps, but avoid expanding into
large reference content.

## Verification

### Content checks
- Every skill has valid `name` and non-empty `description`
- Every `description` includes what + when
- Terminology remains consistent across all 7 skills
- No skill body exceeds 500 lines

### Project checks
- `uv run ruff check .`
- `uv run ruff format . --check`
- `uv run pytest`

## Risks and Mitigations

- Risk: Over-expanding skill bodies.
  - Mitigation: Keep edits focused and concise.
- Risk: Trigger wording becomes inconsistent.
  - Mitigation: Apply one description pattern across all skills.
- Risk: Behavioral drift in skill selection.
  - Mitigation: Preserve original intent; only improve discoverability wording.
