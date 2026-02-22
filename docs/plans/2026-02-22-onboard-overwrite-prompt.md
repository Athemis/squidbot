# Onboard Wizard — Overwrite Prompt Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** When `squidbot onboard` encounters existing workspace files, ask "Overwrite all? [y/N]" and fall back to per-file prompts if the user answers `n`.

**Architecture:** Modify `_run_onboard` in `squidbot/cli/main.py` (lines 756–763) to split files into `missing` and `existing`, then apply overwrite logic before copying. No new abstractions needed.

**Tech Stack:** Python 3.14, pytest, unittest.mock

---

### Task 1: Failing tests for overwrite-all prompt

**Files:**
- Modify: `tests/adapters/test_onboard.py`

**Step 1: Add four new failing tests at the end of the file**

```python
# ── Overwrite prompt ──────────────────────────────────────────────────────────


async def test_onboard_overwrite_all_yes_replaces_existing_files(tmp_path: Path) -> None:
    """'y' to overwrite-all → existing files are replaced with bundled templates."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SOUL.md").write_text("old soul", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("old agents", encoding="utf-8")

    settings = _make_settings(workspace)
    with (
        patch("squidbot.cli.main.input", side_effect=["", "", "", "y"]),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    assert (workspace / "SOUL.md").read_text(encoding="utf-8") != "old soul"
    assert (workspace / "AGENTS.md").read_text(encoding="utf-8") != "old agents"


async def test_onboard_overwrite_all_no_then_per_file_yes_replaces(tmp_path: Path) -> None:
    """'n' to overwrite-all, then 'y' per file → that file is replaced."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SOUL.md").write_text("old soul", encoding="utf-8")

    settings = _make_settings(workspace)
    # inputs: api_base, api_key, model, overwrite_all=n, overwrite_SOUL.md=y
    with (
        patch("squidbot.cli.main.input", side_effect=["", "", "", "n", "y"]),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    assert (workspace / "SOUL.md").read_text(encoding="utf-8") != "old soul"


async def test_onboard_overwrite_all_no_then_per_file_no_keeps(tmp_path: Path) -> None:
    """'n' to overwrite-all, then 'n' per file → file is kept."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SOUL.md").write_text("old soul", encoding="utf-8")

    settings = _make_settings(workspace)
    # inputs: api_base, api_key, model, overwrite_all=n, overwrite_SOUL.md=n
    with (
        patch("squidbot.cli.main.input", side_effect=["", "", "", "n", "n"]),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    assert (workspace / "SOUL.md").read_text(encoding="utf-8") == "old soul"


async def test_onboard_no_overwrite_prompt_when_no_existing_files(tmp_path: Path) -> None:
    """Fresh workspace (no existing files) → no overwrite prompt shown."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"

    prompts: list[str] = []

    def capturing_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return ""

    settings = _make_settings(workspace)
    with (
        patch("squidbot.cli.main.input", side_effect=capturing_input),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    assert not any("overwrite" in p.lower() for p in prompts)
```

**Step 2: Run the new tests to verify they all fail**

```bash
uv run pytest tests/adapters/test_onboard.py -k "overwrite" -v
```

Expected: 4 FAILED (function not yet changed)

**Step 3: Commit the failing tests**

```bash
git add tests/adapters/test_onboard.py
git commit -m "test: add failing tests for onboard overwrite prompt"
```

---

### Task 2: Implement overwrite-prompt logic

**Files:**
- Modify: `squidbot/cli/main.py:756–763`

**Step 1: Replace the copy loop (lines 756–763) with the new logic**

Find this block:

```python
    # Copy bootstrap files from bundled workspace (skip if already present)
    for filename in BOOTSTRAP_FILES_MAIN:
        file_path = workspace / filename
        if not file_path.exists():
            template_path = _BUNDLED_WORKSPACE / filename
            if template_path.exists():
                file_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
                print(f"Created {file_path}")
```

Replace with:

```python
    # Copy bootstrap files from bundled workspace
    missing = [f for f in BOOTSTRAP_FILES_MAIN if not (workspace / f).exists()]
    existing = [f for f in BOOTSTRAP_FILES_MAIN if (workspace / f).exists()]

    # Missing files are created silently
    for filename in missing:
        template_path = _BUNDLED_WORKSPACE / filename
        if template_path.exists():
            (workspace / filename).write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"Created {workspace / filename}")

    # Existing files: ask to overwrite
    if existing:
        listed = ", ".join(existing)
        overwrite_all = input(f"\nExisting files: {listed}. Overwrite all? [y/N] ").strip().lower()
        for filename in existing:
            if overwrite_all == "y":
                do_overwrite = True
            else:
                do_overwrite = input(f"Overwrite {filename}? [y/N] ").strip().lower() == "y"
            if do_overwrite:
                template_path = _BUNDLED_WORKSPACE / filename
                if template_path.exists():
                    (workspace / filename).write_text(
                        template_path.read_text(encoding="utf-8"), encoding="utf-8"
                    )
                    print(f"Updated {workspace / filename}")
```

**Step 2: Run only the new tests**

```bash
uv run pytest tests/adapters/test_onboard.py -k "overwrite" -v
```

Expected: 4 PASSED

**Step 3: Run the full test suite**

```bash
uv run ruff check . && uv run mypy squidbot/ && uv run pytest -q
```

Expected: all checks pass, all existing tests still green.

Note: `test_onboard_does_not_overwrite_existing_files` uses `side_effect=["", "", "", "N"]` — the 4th input `"N"` now goes to the new "Overwrite all?" prompt (not the bootstrap re-run prompt). That test has `AGENTS.md` and `IDENTITY.md` present, so the overwrite-all prompt fires. The bootstrap re-run prompt does NOT fire in that scenario (because `IDENTITY.md` was pre-existing before the wizard ran, and `already_set_up` is computed before copying — no `BOOTSTRAP.md` was present but the wizard is not in `already_set_up` state because the `already_set_up` check fires BEFORE the copy loop). Wait — re-check:

- `already_set_up = (workspace / "IDENTITY.md").exists() and not bootstrap_path.exists()`
- In that test, `IDENTITY.md` IS pre-existing and `BOOTSTRAP.md` is absent → `already_set_up = True`
- So the bootstrap re-run prompt WILL fire too, after the overwrite-all prompt

This means `test_onboard_does_not_overwrite_existing_files` needs a 5th input value: `"N"` for the bootstrap re-run prompt. Update that test:

```python
# old:
patch("squidbot.cli.main.input", side_effect=["", "", "", "N"]),
# new:
patch("squidbot.cli.main.input", side_effect=["", "", "", "N", "N"]),
```

Similarly, `test_onboard_offers_bootstrap_rerun_when_already_set_up` and the two `test_onboard_bootstrap_rerun_*` tests all pre-create `IDENTITY.md` — that means the overwrite-all prompt fires for `IDENTITY.md` before the bootstrap re-run prompt. All of those tests need an extra input for the new overwrite-all prompt inserted BEFORE the bootstrap re-run answer.

Current input sequences (after api_base/api_key/model, i.e. position 4 onward):
- `test_onboard_offers_bootstrap_rerun_when_already_set_up`: `inputs = ["", "", "", "N"]` → needs `["", "", "", "N", "N"]` (overwrite-all=N, bootstrap-rerun=N)
- `test_onboard_bootstrap_rerun_yes_creates_file`: `["", "", "", "y"]` → needs `["", "", "", "N", "y"]` (overwrite-all=N, bootstrap-rerun=y)
- `test_onboard_bootstrap_rerun_no_does_not_create_file`: `["", "", "", "N"]` → needs `["", "", "", "N", "N"]` (overwrite-all=N, bootstrap-rerun=N)

Also `test_onboard_existing_config_kept_on_empty_input` second run has `side_effect=["", "", "", "N"]` — on second run, all `BOOTSTRAP_FILES_MAIN` are present, so `existing` will be non-empty → overwrite-all prompt fires. Needs `["", "", "", "N", "N"]` (overwrite-all=N, bootstrap-rerun=N — IDENTITY.md was created on first run).

And `test_onboard_existing_config_overwritten_with_new_input` second run: `side_effect=["https://second.example.com/v1", "sk-second", "gpt-4o", "N"]` → same situation: `["https://second.example.com/v1", "sk-second", "gpt-4o", "N", "N"]`.

**Step 4: Update all affected existing tests as described above**

Files to update: `tests/adapters/test_onboard.py` lines 96, 136, 187, 232 (inputs list), 270, 294.

After updating, re-run:

```bash
uv run pytest tests/adapters/test_onboard.py -v
```

Expected: all pass.

**Step 5: Run full suite one more time**

```bash
uv run ruff check . && uv run mypy squidbot/ && uv run pytest -q
```

Expected: all green.

**Step 6: Commit**

```bash
git add squidbot/cli/main.py tests/adapters/test_onboard.py
git commit -m "feat: prompt to overwrite existing workspace files in onboard wizard"
```
