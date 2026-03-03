# Matrix Math Rollback Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Revert PRs #65, #57, and #56, then remove only `plugin_mx_math` from the PR #54 scope while keeping Matrix spoiler plugins and HTML sanitization intact.

**Architecture:** Apply explicit git reverts for the three math follow-up PRs to restore pre-follow-up behavior, then perform a targeted code change that unregisters/removes the math plugin integration introduced in PR #54. Keep `plugin_mx_spoiler`, `plugin_mx_block_spoiler`, and `sanitize_for_matrix` unchanged in behavior and wiring.

**Tech Stack:** Python 3.14, mistune, nh3, pytest, ruff, mypy, git, gh CLI.

---

### Task 1: Create a clean rollback branch from main

**Files:**
- Modify: git branch state only

**Step 1: Sync remotes and local main**

Run: `git fetch origin && git checkout main && git pull --ff-only`
Expected: local `main` matches `origin/main`.

**Step 2: Create rollback branch**

Run: `git checkout -b revert/matrix-math-plugin-series`
Expected: new branch active.

**Step 3: Commit**

No commit in this task.

### Task 2: Revert merged PR commits #65, #57, #56

**Files:**
- Modify: files touched by git revert for merge commits

**Step 1: Revert PR #65 merge commit**

Run: `git revert -m 1 d342fe556313ef55352a43c20f45a82245aab6d0`
Expected: revert commit created or conflicts reported.

**Step 2: Revert PR #57 merge commit**

Run: `git revert -m 1 856a316f7bce02998e8b40bab49ba3c4ecc2773c`
Expected: revert commit created or conflicts reported.

**Step 3: Revert PR #56 merge commit**

Run: `git revert -m 1 8857e75a007e30d7365b81951dc9e63c576865df`
Expected: revert commit created or conflicts reported.

**Step 4: Resolve conflicts if present**

Run: `git status` and resolve conflicts minimally.
Expected: clean index with revert sequence completed.

**Step 5: Commit**

If revert paused for conflicts, use: `git add <resolved-files> && git revert --continue`.

### Task 3: Remove only Matrix math plugin integration from PR #54 scope

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Modify: `squidbot/adapters/channels/matrix_markdown.py`
- Modify: `tests/adapters/channels/test_markdown_plugins.py`
- Modify: `tests/adapters/channels/test_matrix.py` (only if expectations depend on math plugin)

**Step 1: Write/adjust failing tests first (TDD)**

Update tests to assert that Matrix output no longer contains `data-mx-maths` while spoiler behavior remains unchanged.

**Step 2: Run targeted tests to verify failure**

Run: `uv run pytest tests/adapters/channels/test_markdown_plugins.py tests/adapters/channels/test_matrix.py -v`
Expected: failures tied to removed math behavior.

**Step 3: Apply minimal implementation**

- Remove `plugin_mx_math` import and registration from Matrix markdown pipeline.
- Remove math plugin code paths from `matrix_markdown.py` while preserving spoiler plugins and sanitizer.

**Step 4: Run targeted tests to verify pass**

Run: `uv run pytest tests/adapters/channels/test_markdown_plugins.py tests/adapters/channels/test_matrix.py -v`
Expected: pass.

**Step 5: Commit**

Run:
`git add squidbot/adapters/channels/matrix.py squidbot/adapters/channels/matrix_markdown.py tests/adapters/channels/test_markdown_plugins.py tests/adapters/channels/test_matrix.py`
`git commit -m "refactor(matrix): remove mx math plugin while keeping spoiler and sanitizer"`

### Task 4: Full verification

**Files:**
- Modify: none

**Step 1: Lint**

Run: `uv run ruff check .`
Expected: no issues.

**Step 2: Format check**

Run: `uv run ruff format . --check`
Expected: no formatting changes required.

**Step 3: Type-check**

Run: `uv run mypy squidbot/`
Expected: success.

**Step 4: Test suite**

Run: `uv run pytest`
Expected: all tests pass.

### Task 5: Publish PR

**Files:**
- Modify: git metadata and GitHub PR only

**Step 1: Push branch**

Run: `git push -u origin revert/matrix-math-plugin-series`
Expected: remote branch created.

**Step 2: Create PR**

Run `gh pr create` with summary:
- Revert PRs #65, #57, #56
- Remove `plugin_mx_math` integration from Matrix path
- Keep spoiler plugins and sanitizer unchanged

**Step 3: Report PR URL**

Post the PR link for review.
