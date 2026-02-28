# Design: Bundled tmux Skill + OpenClaw Compatibility

## Date

2026-02-28

## Status

Approved

## Goal

Deliver a squidbot-native bundled `tmux` skill while keeping external OpenClaw skill adoption easy
through loader-level metadata compatibility.

## Context

The OpenClaw `tmux` skill is a good functional template, but bundled squidbot skills should follow
squidbot conventions for frontmatter and examples. At the same time, users should still be able to
drop in external OpenClaw skills without manual metadata rewrites.

Current loader behavior in `squidbot/adapters/skills/fs.py`:
- Parses skill frontmatter from `SKILL.md`.
- Checks requirement availability via `_check_availability()`.
- Reads `requires.bins` and `requires.env` only from top-level `requires`.

Resulting gaps:
- Bundled `tmux` should be rewritten to squidbot-native style instead of shipping upstream shape.
- External OpenClaw skills can load, but requirement checks may miss required binaries/env vars.

## Approaches Considered

### A. Split strategy: native bundled tmux + compatibility fallback (selected)

Ship a squidbot-native bundled `tmux` skill and add loader fallback for OpenClaw metadata.

Pros:
- Best UX for bundled skill quality and consistency
- Keeps external OpenClaw adoption low-friction
- Avoids forcing users to rewrite imported skills

Cons:
- Slightly larger scope than changing only one side

### B. Bundled-only rewrite

Rewrite bundled `tmux` as squidbot-native, without compatibility fallback.

Pros:
- Smallest immediate code footprint

Cons:
- External OpenClaw skills still need manual adaptation

### C. Compatibility-only

Only add loader fallback and keep bundled content close to upstream.

Pros:
- Fastest path for import compatibility

Cons:
- Bundled skill remains less tailored to squidbot usage

## Selected Design

Implement Approach A.

### Architecture

- Keep `SkillMetadata` unchanged in `squidbot/core/skills.py`.
- Add bundled `tmux` skill at `squidbot/skills/tmux/SKILL.md` in squidbot-native format.
- Add schema-compatibility extraction in `squidbot/adapters/skills/fs.py`.
- Maintain first-class support for squidbot-native frontmatter.

### Components

- `squidbot/skills/tmux/SKILL.md`:
  - top-level squidbot frontmatter (`name`, `description`, `requires.bins`)
  - squidbot-oriented command examples and guardrails
- Internal helper in `squidbot/adapters/skills/fs.py` (e.g. `_extract_requires`) that normalizes
  `bins/env` from:
  1. top-level `requires`
  2. fallback `metadata.openclaw.requires`
- Keep `_check_availability()` as the single place that computes missing bins/env and availability.

### Data Flow

1. Bundled `tmux` loads from squidbot skills directory with top-level `requires`.
2. For external OpenClaw skills, frontmatter is parsed with `_parse_frontmatter()`.
3. Normalized `requires` values are extracted (top-level first, OpenClaw fallback second).
4. Availability is computed from normalized lists.
5. `SkillMetadata.requires_bins` and `SkillMetadata.requires_env` are populated consistently
   regardless of source schema.

### Precedence Rules

- If top-level `requires` contains usable data, it takes precedence.
- If not, fallback to `metadata.openclaw.requires`.
- If neither path contains valid lists, treat as no requirements.

## Error Handling

- Keep loader fault-tolerant: malformed or partial metadata must not crash full skill discovery.
- Invalid `requires` types (e.g., string instead of list) normalize to empty lists.
- Missing nested keys in OpenClaw metadata are treated as absent requirements.
- Bundled `tmux` wording is explicit about safe tmux targeting to reduce operator mistakes.

## Testing Strategy (TDD)

Add/extend tests to cover:
- Bundled `tmux` skill discoverability and basic metadata validity.
- Top-level `requires` extraction and availability checks.
- OpenClaw fallback extraction from `metadata.openclaw.requires`.
- Precedence behavior when both schemas are present.
- Robust handling of invalid types and missing keys.

Success criteria:
- Existing tests remain green.
- Bundled `tmux` is squidbot-native and discoverable.
- New tests validate both metadata shapes.
- OpenClaw `tmux`-style skill metadata is interpreted correctly without manual rewrite.

## Non-Goals

- No broad multi-vendor metadata abstraction beyond OpenClaw fallback.
- No changes to core architecture or system prompt format.
- No automatic external repository sync/import tooling.

## Validation Commands

- `uv run ruff check .`
- `uv run ruff format . --check`
- `uv run pytest`
