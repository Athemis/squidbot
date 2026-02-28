# Design: OpenClaw Skill Metadata Compatibility

## Date

2026-02-28

## Status

Approved

## Goal

Enable squidbot to adopt OpenClaw-style skills with minimal friction by adding compatibility for
their metadata shape, while preserving existing squidbot skill behavior.

## Context

The `tmux` skill from OpenClaw is a good candidate for reuse. Its frontmatter expresses
requirements under `metadata.openclaw.requires`, while squidbot currently reads requirements from
top-level `requires` only.

Current loader behavior in `squidbot/adapters/skills/fs.py`:
- Parses skill frontmatter from `SKILL.md`.
- Checks requirement availability via `_check_availability()`.
- Reads `requires.bins` and `requires.env` only from top-level `requires`.

Resulting gap:
- OpenClaw skills can load, but requirement checks may silently miss required binaries/env vars.

## Approaches Considered

### A. Loader compatibility layer (selected)

Teach squidbot's skills loader to read `requires` from multiple schema locations:
- `requires` (existing squidbot schema)
- `metadata.openclaw.requires` (OpenClaw schema fallback)

Pros:
- Minimal user friction for external skill adoption
- Keeps existing squidbot skills unchanged
- Centralized logic in one adapter

Cons:
- Slightly more parsing logic in loader

### B. Import-time normalization

Use a separate import script to rewrite external frontmatter into squidbot schema.

Pros:
- Core loader remains simpler

Cons:
- Adds separate import/update workflow
- More maintenance overhead over time

### C. Hybrid compatibility + importer

Add loader fallback and optional import helper.

Pros:
- Most flexible long-term

Cons:
- Larger initial scope than needed

## Selected Design

Implement Approach A.

### Architecture

- Keep `SkillMetadata` unchanged in `squidbot/core/skills.py`.
- Add schema-compatibility extraction in `squidbot/adapters/skills/fs.py`.
- Maintain first-class support for squidbot-native frontmatter.

### Components

- Add an internal helper (name TBD, e.g. `_extract_requires`) to normalize `bins/env` from:
  1. top-level `requires`
  2. fallback `metadata.openclaw.requires`
- Keep `_check_availability()` as the single place that computes missing bins/env and availability.

### Data Flow

1. Parse frontmatter with `_parse_frontmatter()`.
2. Extract normalized `requires` values (top-level first, OpenClaw fallback second).
3. Compute availability based on normalized lists.
4. Populate `SkillMetadata.requires_bins` and `SkillMetadata.requires_env` consistently regardless of
   source schema.

### Precedence Rules

- If top-level `requires` contains usable data, it takes precedence.
- If not, fallback to `metadata.openclaw.requires`.
- If neither path contains valid lists, treat as no requirements.

## Error Handling

- Keep loader fault-tolerant: malformed or partial metadata must not crash full skill discovery.
- Invalid `requires` types (e.g., string instead of list) normalize to empty lists.
- Missing nested keys in OpenClaw metadata are treated as absent requirements.

## Testing Strategy (TDD)

Add/extend adapter tests to cover:
- Top-level `requires` extraction and availability checks.
- OpenClaw fallback extraction from `metadata.openclaw.requires`.
- Precedence behavior when both schemas are present.
- Robust handling of invalid types and missing keys.

Success criteria:
- Existing tests remain green.
- New tests validate both metadata shapes.
- OpenClaw `tmux`-style skill metadata is interpreted correctly without manual rewrite.

## Non-Goals

- No broad multi-vendor metadata abstraction in this step.
- No changes to core architecture or system prompt format.
- No automatic external repository sync/import tooling.

## Validation Commands

- `uv run ruff check .`
- `uv run ruff format . --check`
- `uv run pytest`
