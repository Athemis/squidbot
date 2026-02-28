---
name: skill-creator
description: "Creates new skills by writing `SKILL.md` files with valid frontmatter and concise instructions. Use when adding or updating reusable agent skills."
always: false
requires: {}
---

# Skill Creator

## When to Use

- A new reusable capability should be packaged as a skill.
- An existing skill needs a clear, maintainable rewrite.

## Core Principles

- Keep `SKILL.md` concise; include only non-obvious guidance.
- Put discovery cues in `description` (what it does + when to use it).
- Prefer one clear default workflow over many alternatives.
- Keep references one level deep from `SKILL.md`.

## Workflow

1. Create the directory: `workspace/skills/<name>/`.
2. Write `workspace/skills/<name>/SKILL.md`.
3. Add required frontmatter (`name`, `description`) and optional fields (`always`, `requires`).
4. Write concise, actionable instructions in imperative style.
5. Add resource folders only if needed (`scripts/`, `references/`, `assets/`).
6. Verify naming and description quality before saving.

## Canonical Frontmatter

```yaml
---
name: example-skill
description: "Performs X. Use when Y."
always: false
requires: {}
---
```

`name` and `description` are the core required fields. `always` and `requires` are
squidbot-specific extensions supported by this project.

## Validation Checklist

- `name` uses lowercase letters, numbers, or hyphens only.
- `name` stays under 64 characters.
- `description` explains what the skill does and when to use it.
- `description` is in third person and avoids vague wording.
- Instructions are concise and avoid unnecessary background text.
- `SKILL.md` body stays under ~500 lines.

## References

- Claude skill best practices:
  <https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices.md>
- Agent Skills specification:
  <https://agentskills.io/specification.md>
