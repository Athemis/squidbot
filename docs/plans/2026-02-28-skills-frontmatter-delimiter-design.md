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

Detect frontmatter delimiters as root-level fence lines:
- file must start with an exact fence line (`---`)
- closing delimiter is the next exact root-level fence line (`---`)
- indented `---` lines inside YAML content are never treated as delimiters

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
- Replace substring-based closing-delimiter detection with exact root-level line detection in
  `_parse_frontmatter()` (`line.rstrip("\r") == "---"`, no `.strip()`).
- Leave loader behavior unchanged outside frontmatter extraction.

### Data Flow

1. Read file text from `SKILL.md`.
2. Verify file begins with an exact root-level frontmatter fence line.
3. Scan forward line-by-line for the next exact root-level fence line.
4. Join intervening lines as YAML block and parse with `ruamel.yaml`.
5. Return parsed metadata dict or `{}` when no valid frontmatter block exists.

### Error Handling

- If opening delimiter is missing: return `{}`.
- If closing standalone delimiter is missing: return `{}`.
- YAML parse errors continue to be handled by `_load_cached()` fail-safe behavior (skill skipped,
  loader continues).

### Behavior Contract

- Missing opening delimiter -> `_parse_frontmatter()` returns `{}`; loader keeps skill with fallback
  defaults.
- Missing closing delimiter -> `_parse_frontmatter()` returns `{}`; loader keeps skill with fallback
  defaults.
- Malformed YAML between delimiters -> YAML parse error is caught by `_load_cached()` fail-safe;
  skill entry is skipped.
- Delimiter policy is strict: accepted fence is exact root-level `---` line (`line.rstrip("\\r") ==
  "---"`). Leading whitespace, trailing spaces, or BOM-prefixed opener are treated as
  non-delimiters.
- Extracted YAML content is passed to `ruamel.yaml` without additional `.strip()` normalization, so
  boundary whitespace semantics stay parser-native.

## Testing Strategy (TDD)

Add focused regression coverage in `tests/core/test_skills.py`:

1. **Primary regression**
   - Frontmatter with `description: "contains --- inside"` and valid closing delimiter line.
   - Expect skill metadata to load correctly.

2. **Block scalar regression**
   - Frontmatter with YAML block scalar containing an indented `---` line.
   - Expect indented `---` to remain content, not delimiter.

3. **Defensive malformed-frontmatter cases (required)**
   - Missing closing delimiter line.
   - Missing opening delimiter line.
   - Malformed YAML between delimiters.
   - Expect no crash and documented fallback behavior.

### Traceability Matrix

| Behavior contract requirement | Planned test(s) | Plan task |
|---|---|---|
| Quoted string contains `---` | `test_frontmatter_parsing_ignores_triple_dash_inside_yaml_string` | Task 1 |
| Indented `---` in block scalar remains content | `test_frontmatter_parsing_ignores_indented_triple_dash_in_block_scalar` | Task 1 |
| Missing opening delimiter => fallback defaults | `test_frontmatter_without_opening_delimiter_uses_fallback_defaults` | Task 3 |
| Missing closing delimiter => fallback defaults | `test_frontmatter_without_closing_delimiter_returns_no_metadata` | Task 3 |
| Malformed YAML => fail-safe skip | `test_malformed_frontmatter_yaml_is_skipped_without_crash` | Task 3 |
| Strict fence: leading/trailing whitespace, BOM not delimiters | strict-fence tests in Task 3 Step 4 | Task 3 |
| CRLF fence compatibility | CRLF-specific strict-fence test in Task 3 Step 4 | Task 3 |
| YAML boundary whitespace preserved | block-scalar boundary whitespace regression in Task 3 | Task 3 |

Success criteria:
- New regression test fails on old logic and passes on new logic.
- Existing skill tests remain green.
- `_parse_frontmatter()` branch behavior is covered for opener missing, closer missing, valid block,
  and malformed YAML.
- CRLF frontmatter delimiters are covered by explicit regression tests.

## Scope

In scope:
- `_parse_frontmatter()` delimiter hardening
- required regression + defensive coverage:
  - quoted-string `---`
  - indented `---` inside YAML block scalar
  - missing opening delimiter
  - missing closing delimiter
  - malformed YAML fail-safe

Out of scope:
- Cache/discovery refactors
- Metadata schema changes
- Generic frontmatter framework redesign

## Validation Commands

- `uv run ruff check .`
- `uv run ruff format . --check`
- `uv run pytest`
- `uv run mypy squidbot/`
