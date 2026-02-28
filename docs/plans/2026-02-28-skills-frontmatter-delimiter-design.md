# Design: Skills Frontmatter Delimiter Hardening

## Date

2026-02-28

## Status

Approved

## Goal

Fix frontmatter parsing in the skills loader so `---` inside YAML string values does not break
metadata extraction.

## Context

`_parse_frontmatter()` in `squidbot/adapters/skills/fs.py` currently finds the closing delimiter with
`text.find("---", 3)`. This can incorrectly match `---` that appears inside YAML string content,
which truncates the YAML block and can cause parsing failure.

The project already uses `ruamel.yaml` for YAML parsing. The issue is not YAML parsing itself, but
delimiter detection before parsing.

## Approaches Considered

### A. Line-based delimiter extraction + ruamel parsing (selected)

Detect frontmatter delimiters as standalone lines:
- file must start with a delimiter line (`---`)
- closing delimiter is the next standalone delimiter line

Then parse only the extracted YAML block with `ruamel.yaml`.

Pros:
- Robust against `---` within YAML string values
- Easy to read and maintain
- Minimal scope and low regression risk

Cons:
- Slightly more code than naive substring search

### B. Regex extraction for full block

Extract frontmatter via regex and pass match to YAML parser.

Pros:
- Compact implementation

Cons:
- Harder to reason about across edge cases and line-ending variants

### C. Larger parser refactor

Rework frontmatter processing into a broader parsing abstraction.

Pros:
- Potentially more extensible long-term

Cons:
- Overkill for current bug (YAGNI)
- Increased scope and risk

## Selected Design

Implement Approach A.

### Architecture

- Keep `ruamel.yaml` as the YAML parser.
- Replace substring-based closing-delimiter detection with line-based delimiter detection in
  `_parse_frontmatter()`.
- Leave loader behavior unchanged outside frontmatter extraction.

### Data Flow

1. Read file text from `SKILL.md`.
2. Verify file begins with a standalone frontmatter delimiter line.
3. Scan forward line-by-line for the next standalone delimiter line.
4. Join intervening lines as YAML block and parse with `ruamel.yaml`.
5. Return parsed metadata dict or `{}` when no valid frontmatter block exists.

### Error Handling

- If opening delimiter is missing: return `{}`.
- If closing standalone delimiter is missing: return `{}`.
- YAML parse errors continue to be handled by `_load_cached()` fail-safe behavior (skill skipped,
  loader continues).

## Testing Strategy (TDD)

Add focused regression coverage in `tests/core/test_skills.py`:

1. **Primary regression**
   - Frontmatter with `description: "contains --- inside"` and valid closing delimiter line.
   - Expect skill metadata to load correctly.

2. **Defensive case (optional but preferred)**
   - File that starts frontmatter but lacks a closing standalone delimiter line.
   - Expect no crash and graceful fallback behavior.

Success criteria:
- New regression test fails on old logic and passes on new logic.
- Existing skill tests remain green.

## Scope

In scope:
- `_parse_frontmatter()` delimiter hardening
- 1-2 focused regression tests

Out of scope:
- Cache/discovery refactors
- Metadata schema changes
- Generic frontmatter framework redesign

## Validation Commands

- `uv run ruff check .`
- `uv run ruff format . --check`
- `uv run pytest`
