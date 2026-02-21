---
name: skill-creator
description: "Create new skills by writing SKILL.md files to the workspace."
always: false
requires: {}
---

# Skill Creator

To create a new skill, write a `SKILL.md` file to `workspace/skills/<name>/SKILL.md` using the `write_file` tool. The frontmatter must include `name`, `description`, and optionally `always` and `requires`.
