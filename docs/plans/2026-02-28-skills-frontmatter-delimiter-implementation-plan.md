# Skills Frontmatter Delimiter Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make skills frontmatter parsing robust when `---` appears inside YAML string values.

**Architecture:** Keep `ruamel.yaml` as the YAML parser, but change delimiter extraction in `_parse_frontmatter()` to detect standalone delimiter lines instead of substring matches. Add focused regression tests that first fail with current delimiter logic and then pass with the hardened implementation.

**Tech Stack:** Python 3.14, pytest, ruamel.yaml, ruff.

---

### Task 1: Add regression test for delimiter inside YAML string

**Files:**
- Modify: `tests/core/test_skills.py`
- Modify later: `squidbot/adapters/skills/fs.py`

**Step 1: Write the failing test**

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

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_skills.py::test_frontmatter_parsing_ignores_triple_dash_inside_yaml_string -v`
Expected: FAIL (old parser closes frontmatter too early).

**Step 3: Commit test-only change**

```bash
git add tests/core/test_skills.py
git commit -m "test(skills): add regression for frontmatter delimiter in strings"
```

### Task 2: Harden `_parse_frontmatter()` delimiter extraction

**Files:**
- Modify: `squidbot/adapters/skills/fs.py`
- Test: `tests/core/test_skills.py`

**Step 1: Implement minimal parser hardening**

Replace substring delimiter search with line-based delimiter detection in `_parse_frontmatter()`:

```python
def _parse_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    closing_index = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            closing_index = idx
            break
    if closing_index == -1:
        return {}

    yaml_block = "\n".join(lines[1:closing_index]).strip()
    data = _yaml.load(yaml_block)
    return dict(data) if data else {}
```

Keep `ruamel.yaml` parsing unchanged.

**Step 2: Run targeted tests**

Run: `uv run pytest tests/core/test_skills.py -v`
Expected: PASS including the new regression test.

**Step 3: Commit implementation**

```bash
git add squidbot/adapters/skills/fs.py tests/core/test_skills.py
git commit -m "fix(skills): parse frontmatter delimiters by line"
```

### Task 3: Add optional defensive missing-closer test

**Files:**
- Modify: `tests/core/test_skills.py`

**Step 1: Write defensive test**

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

**Step 2: Run targeted tests**

Run: `uv run pytest tests/core/test_skills.py -v`
Expected: PASS.

**Step 3: Commit test addition**

```bash
git add tests/core/test_skills.py
git commit -m "test(skills): cover missing frontmatter closing delimiter"
```

### Task 4: Run full project verification

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

**Step 4: Final commit only if verification changed files**

```bash
git add -A
git commit -m "chore(skills): finalize frontmatter parser hardening"
```

Create this commit only if verification introduces additional edits.
