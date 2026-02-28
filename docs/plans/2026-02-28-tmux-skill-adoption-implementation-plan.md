# tmux Skill Adoption Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship a squidbot-native bundled `tmux` skill and add loader compatibility for external OpenClaw skill metadata.

**Architecture:** Keep the core `SkillMetadata` model unchanged, then handle schema compatibility inside the filesystem skills loader. Add a bundled `squidbot/skills/tmux/SKILL.md` that follows squidbot frontmatter conventions and tmux-safe operating guidance.

**Tech Stack:** Python 3.14, pytest, ruamel.yaml, existing squidbot skills loader/CLI.

---

### Task 1: Add failing loader compatibility tests

**Files:**
- Modify: `tests/core/test_skills.py`
- Modify: `squidbot/adapters/skills/fs.py` (later task)

**Step 1: Write the failing tests**

Add tests that currently fail because loader only reads top-level `requires`:

```python
def test_openclaw_requires_fallback_marks_skill_unavailable(tmp_path):
    skill = tmp_path / "tmux"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: tmux\n"
        "description: 'tmux skill'\n"
        "metadata:\n"
        "  openclaw:\n"
        "    requires:\n"
        "      bins: [__definitely_missing_tmux_bin__]\n"
        "---\n",
        encoding="utf-8",
    )
    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()
    assert skills[0].available is False
    assert "__definitely_missing_tmux_bin__" in skills[0].requires_bins


def test_top_level_requires_precedence_over_openclaw(tmp_path):
    ...


def test_invalid_requires_shapes_do_not_crash(tmp_path):
    ...
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_skills.py::test_openclaw_requires_fallback_marks_skill_unavailable -v`
Expected: FAIL because missing bin is not detected from `metadata.openclaw.requires`.

**Step 3: Commit test-only change**

```bash
git add tests/core/test_skills.py
git commit -m "test(skills): cover openclaw metadata requires fallback"
```

### Task 2: Implement compatibility extraction in loader

**Files:**
- Modify: `squidbot/adapters/skills/fs.py`
- Test: `tests/core/test_skills.py`

**Step 1: Write minimal implementation**

Add a helper that normalizes `requires` from top-level first, then OpenClaw fallback:

```python
def _extract_requires(meta: dict[str, Any]) -> tuple[list[str], list[str]]:
    requires = meta.get("requires")
    if not isinstance(requires, dict):
        requires = (
            (meta.get("metadata") or {})
            .get("openclaw", {})
            .get("requires", {})
        )

    bins_raw = requires.get("bins", []) if isinstance(requires, dict) else []
    env_raw = requires.get("env", []) if isinstance(requires, dict) else []

    bins = [v for v in bins_raw if isinstance(v, str)] if isinstance(bins_raw, list) else []
    envs = [v for v in env_raw if isinstance(v, str)] if isinstance(env_raw, list) else []
    return bins, envs
```

Update `_check_availability()` to call this helper.

**Step 2: Run targeted tests**

Run: `uv run pytest tests/core/test_skills.py -v`
Expected: PASS for new compatibility tests and existing skills tests.

**Step 3: Commit implementation**

```bash
git add squidbot/adapters/skills/fs.py tests/core/test_skills.py
git commit -m "feat(skills): support openclaw requires metadata fallback"
```

### Task 3: Add bundled squidbot-native tmux skill

**Files:**
- Create: `squidbot/skills/tmux/SKILL.md`
- Modify: `tests/core/test_skills.py`

**Step 1: Add failing discoverability test for bundled tmux**

Add a test that expects bundled skill presence from the package skills directory:

```python
def test_bundled_tmux_skill_is_discoverable() -> None:
    bundled_dir = Path(__file__).resolve().parents[2] / "squidbot" / "skills"
    loader = FsSkillsLoader(search_dirs=[bundled_dir])
    names = {skill.name for skill in loader.list_skills()}
    assert "tmux" in names
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_skills.py::test_bundled_tmux_skill_is_discoverable -v`
Expected: FAIL until `squidbot/skills/tmux/SKILL.md` exists.

**Step 3: Create squidbot-native tmux skill content**

Create `squidbot/skills/tmux/SKILL.md` with:
- top-level frontmatter fields used by squidbot (`name`, `description`, `always`, `requires`)
- `requires.bins: [tmux]`
- sections for when to use/not use
- safe command patterns for `tmux send-keys` and `tmux capture-pane`
- examples aligned with squidbot tool usage guidance

**Step 4: Run targeted tests**

Run: `uv run pytest tests/core/test_skills.py -v`
Expected: PASS including bundled tmux discoverability test.

**Step 5: Commit bundled skill**

```bash
git add squidbot/skills/tmux/SKILL.md tests/core/test_skills.py
git commit -m "feat(skills): add bundled squidbot-native tmux skill"
```

### Task 4: Verify end-to-end quality gates

**Files:**
- Verify: `squidbot/adapters/skills/fs.py`
- Verify: `squidbot/skills/tmux/SKILL.md`
- Verify: `tests/core/test_skills.py`

**Step 1: Run lint**

Run: `uv run ruff check .`
Expected: PASS with no violations.

**Step 2: Run formatting check**

Run: `uv run ruff format . --check`
Expected: PASS with no reformat needed.

**Step 3: Run full test suite**

Run: `uv run pytest`
Expected: PASS all tests.

**Step 4: Final commit if verification changed files**

```bash
git add -A
git commit -m "chore(skills): finalize tmux adoption verification fixes"
```

Only create this commit if any verification-induced edits are required.
