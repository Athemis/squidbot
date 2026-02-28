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

## Workflow

1. Create the directory: `workspace/skills/<name>/`.
2. Write `workspace/skills/<name>/SKILL.md`.
3. Add frontmatter and concise, actionable instructions.
4. Verify naming and description quality before saving.

## Canonical Frontmatter

```yaml
---
name: example-skill
description: "Performs X. Use when Y."
always: false
requires: {}
---
```

## Validation Checklist

- `name` uses lowercase letters, numbers, or hyphens only.
- `description` explains what the skill does and when to use it.
- Instructions are concise and avoid unnecessary background text.
