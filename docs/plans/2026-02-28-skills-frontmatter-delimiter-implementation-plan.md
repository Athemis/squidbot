# Skills Frontmatter Delimiter Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make skills frontmatter parsing robust when `---` appears inside YAML string values.

**Architecture:** Keep `ruamel.yaml` as the YAML parser, but change delimiter extraction in `_parse_frontmatter()` to detect standalone delimiter lines instead of substring matches. Add focused regression tests that first fail with current delimiter logic and then pass with the hardened implementation.

**Tech Stack:** Python 3.14, pytest, ruamel.yaml, ruff, mypy.

---

## Behavior contract (must remain explicit)

- Missing opening delimiter => `_parse_frontmatter()` returns `{}` and loader keeps skill with
  fallback defaults.
- Missing closing delimiter => `_parse_frontmatter()` returns `{}` and loader keeps skill with
  fallback defaults.
- Malformed YAML between delimiters => parse error is caught in `_load_cached()`; skill is skipped.
- Delimiters are strict root-level fence lines only (`line.rstrip("\\r") == "---"`).
- Lines with leading whitespace, trailing spaces, or BOM-prefixed opener are not delimiters.

## Task 1: Add failing regression tests for delimiter edge cases

**Files:**
- Modify: `tests/core/test_skills.py`
- Modify later: `squidbot/adapters/skills/fs.py`

**Step 1: Write the failing tests**

Add a test that creates `SKILL.md` with frontmatter where `description` includes `---`, then asserts metadata still loads:

```python
def test_frontmatter_parsing_ignores_triple_dash_inside_yaml_string(tmp_path):
    skill = tmp_path / "dashy"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: dashy\n"
        'description: "contains --- inside"\n'
        "---\n"
        "# Dashy Skill\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "dashy"
    assert "contains --- inside" in skills[0].description
```

Add a second test for YAML block scalar content containing an indented `---` line, which must not be treated as a delimiter:

```python
def test_frontmatter_parsing_ignores_indented_triple_dash_in_block_scalar(tmp_path):
    skill = tmp_path / "blocky"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: blocky\n"
        "description: |\n"
        "  first line\n"
        "  ---\n"
        "  last line\n"
        "---\n"
        "# Blocky Skill\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "blocky"
    assert "first line" in skills[0].description
    assert "last line" in skills[0].description
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_skills.py::test_frontmatter_parsing_ignores_triple_dash_inside_yaml_string tests/core/test_skills.py::test_frontmatter_parsing_ignores_indented_triple_dash_in_block_scalar -v`
Expected: at least one new regression test FAILS with old parser behavior.

**Step 3: Optional checkpoint commit**

Create this commit only if local workflow allows a red-state checkpoint; otherwise keep changes local and continue to Task 2.

```bash
git add tests/core/test_skills.py
git commit -m "test(skills): add frontmatter delimiter regression cases"
```

## Task 2: Harden `_parse_frontmatter()` delimiter extraction

**Files:**
- Modify: `squidbot/adapters/skills/fs.py`
- Test: `tests/core/test_skills.py`

**Step 1: Implement minimal parser hardening**

Replace substring delimiter search with root-level line-based delimiter detection in `_parse_frontmatter()`:

```python
def _parse_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].rstrip("\r") != "---":
        return {}

    closing_index = -1
    for idx in range(1, len(lines)):
        line = lines[idx]
        if line.rstrip("\r") == "---":
            closing_index = idx
            break
    if closing_index == -1:
        return {}

    yaml_block = "\n".join(lines[1:closing_index])
    data = _yaml.load(yaml_block)
    return dict(data) if data else {}
```

Notes:
- Delimiters are exact root-level fence lines (`---`), not whitespace-stripped matches.
- Indented `---` remains YAML content and must never close frontmatter.
- Keep `ruamel.yaml` parsing unchanged.

**Step 2: Run targeted tests**

Run: `uv run pytest tests/core/test_skills.py -v`
Expected: PASS including the new regression test.

**Step 3: Commit implementation**

```bash
git add squidbot/adapters/skills/fs.py tests/core/test_skills.py
git commit -m "fix(skills): parse frontmatter delimiters by line"
```

## Task 3: Add required defensive malformed-frontmatter tests

**Files:**
- Modify: `tests/core/test_skills.py`

**Step 1: Add missing-closing-delimiter test**

Add a test for frontmatter with opening delimiter but no closing delimiter line:

```python
def test_frontmatter_without_closing_delimiter_returns_no_metadata(tmp_path):
    skill = tmp_path / "broken"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: broken\n"
        "description: missing closer\n"
        "# body without closing delimiter\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "broken"
    assert skills[0].description == ""
```

**Step 2: Add missing-opening-delimiter test**

Add a test where the file does not start with an opening delimiter. Expect empty frontmatter path and fallback defaults:

```python
def test_frontmatter_without_opening_delimiter_uses_fallback_defaults(tmp_path):
    skill = tmp_path / "plain"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "name: plain\n"
        "description: not-frontmatter\n"
        "# Plain Skill\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "plain"
    assert skills[0].description == ""
```

**Step 3: Add malformed-YAML fail-safe test**

Add a test with invalid YAML between delimiters. Expect no crash and current fail-safe behavior (skill skipped):

```python
def test_malformed_frontmatter_yaml_is_skipped_without_crash(tmp_path):
    skill = tmp_path / "badyaml"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: badyaml\n"
        "description: \"unterminated\n"
        "---\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert skills == []
```

**Step 4: Add strict-fence policy tests**

Add tests that lock down strict delimiter behavior:

```python
def test_frontmatter_with_leading_whitespace_opening_fence_uses_fallback_defaults(tmp_path):
    skill = tmp_path / "ws-open"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        " ---\n"
        "name: ws-open\n"
        "description: should not parse\n"
        "---\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "ws-open"
    assert skills[0].description == ""


def test_frontmatter_with_trailing_space_opening_fence_uses_fallback_defaults(tmp_path):
    skill = tmp_path / "space-open"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "--- \n"
        "name: space-open\n"
        "description: should not parse\n"
        "---\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "space-open"
    assert skills[0].description == ""


def test_frontmatter_with_trailing_space_closing_fence_uses_fallback_defaults(tmp_path):
    skill = tmp_path / "space-close"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: space-close\n"
        "description: should not parse\n"
        "--- \n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "space-close"
    assert skills[0].description == ""


def test_frontmatter_with_bom_prefixed_opening_fence_is_not_treated_as_delimiter(tmp_path):
    skill = tmp_path / "bom-open"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "\ufeff---\n"
        "name: bom-open\n"
        "description: should not parse\n"
        "---\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "bom-open"
    assert skills[0].description == ""


def test_frontmatter_with_crlf_fences_parses_metadata(tmp_path):
    skill = tmp_path / "crlf"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\r\n"
        "name: crlf\r\n"
        'description: "crlf delimiters"\r\n'
        "---\r\n"
        "# CRLF Skill\r\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "crlf"
    assert "crlf delimiters" in skills[0].description


def test_frontmatter_preserves_block_scalar_boundary_blank_lines(tmp_path):
    skill = tmp_path / "boundary"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: boundary\n"
        "description: |\n"
        "\n"
        "  line\n"
        "\n"
        "---\n"
        "# Boundary Skill\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "boundary"
    assert skills[0].description == "\nline\n"
```

Expected boundary behavior:
- `description` preserves the leading and trailing blank line from the block scalar fixture.

Expected behavior for all strict-fence tests:
- `_parse_frontmatter()` returns `{}` path.
- loader keeps skill with fallback defaults (name from dir, empty description).

**Step 5: Run targeted tests**

Run: `uv run pytest tests/core/test_skills.py -v`
Expected: PASS.

**Step 6: Commit test additions**

```bash
git add tests/core/test_skills.py
git commit -m "test(skills): cover malformed frontmatter edge cases"
```

## Task 4: Run full project verification

**Files:**
- Verify: `squidbot/adapters/skills/fs.py`
- Verify: `tests/core/test_skills.py`

**Step 1: Run lint**

Run: `uv run ruff check .`
Expected: PASS.

**Step 2: Run formatting check**

Run: `uv run ruff format . --check`
Expected: PASS.

**Step 3: Run full test suite**

Run: `uv run pytest`
Expected: PASS.

**Step 4: Run type checks**

Run: `uv run mypy squidbot/`
Expected: PASS.

**Step 5: Final commit only if verification changed files**

```bash
git add squidbot/adapters/skills/fs.py tests/core/test_skills.py
git commit -m "chore(skills): finalize frontmatter parser hardening"
```

Create this commit only if verification introduces additional edits.
