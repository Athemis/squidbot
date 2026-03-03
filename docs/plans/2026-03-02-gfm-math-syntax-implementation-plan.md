# GFM Math Syntax Extensions — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the Matrix math plugin to support all three missing GFM math syntax
variants: inline-open block math, backtick inline math, and fenced block math.

**Architecture:** All changes are confined to `matrix_markdown.py` (plugin logic)
and `test_markdown_plugins.py` (tests).  No new dependencies.  TDD throughout —
each task writes a failing test first, then the implementation.

**Tech Stack:** mistune 3.x block/inline plugin API, Python `re` with named groups,
`html.escape`, existing `nh3` sanitizer (unchanged).

**Design doc:** `docs/plans/2026-03-02-gfm-math-syntax-design.md`

---

## Task 1: Failing tests — inline-open block math (Form C)

**Files:**
- Test: `tests/adapters/channels/test_markdown_plugins.py`

**Step 1: Add failing tests inside `TestMatrixMathPlugin`**

Open `tests/adapters/channels/test_markdown_plugins.py`.
Locate the `TestMatrixMathPlugin` class and add these test methods after the last
existing method in that class:

```python
def test_block_math_inline_open_align(self) -> None:
    """$$\\begin{align}...\\end{align}$$ renders as div, not raw $$."""
    src = "$$\\begin{align}\nf(x) &= x + 1\n\\end{align}$$"
    result = _matrix_md(src)
    assert '<div data-mx-maths="' in result
    assert "$$" not in result

def test_block_math_inline_open_bmatrix(self) -> None:
    """$$\\begin{bmatrix}...\\end{bmatrix}$$ renders as div."""
    src = "$$\\begin{bmatrix}\n1 & 2 \\\\\n3 & 4\n\\end{bmatrix}$$"
    result = _matrix_md(src)
    assert '<div data-mx-maths="' in result
    assert "$$" not in result

def test_block_math_inline_open_cases(self) -> None:
    """$$\\begin{cases}...\\end{cases}$$ renders as div."""
    src = "$$\\begin{cases}\nx & x \\geq 0 \\\\\n-x & x < 0\n\\end{cases}$$"
    result = _matrix_md(src)
    assert '<div data-mx-maths="' in result
    assert "$$" not in result

def test_block_math_inline_open_content_preserved(self) -> None:
    """Content between inline-open $$ is preserved verbatim in attribute."""
    src = "$$\\begin{align}\nf(x) &= x + 1\n\\end{align}$$"
    result = _matrix_md(src)
    assert "\\begin{align}" in result
    assert "\\end{align}" in result
```

**Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/adapters/channels/test_markdown_plugins.py::TestMatrixMathPlugin::test_block_math_inline_open_align -v
```

Expected: FAIL — `$$` appears in output, no `<div data-mx-maths`.

**Step 3: Commit the failing tests**

```bash
git add tests/adapters/channels/test_markdown_plugins.py
git commit -m "test: add failing tests for inline-open block math (Form C)"
```

---

## Task 2: Implement — inline-open block math (Form C)

**Files:**
- Modify: `squidbot/adapters/channels/matrix_markdown.py`

**Step 1: Extend `_BLOCK_MATH_PATTERN`**

Find the `_BLOCK_MATH_PATTERN` constant (currently two alternatives joined by `|`).
Replace it with three alternatives:

```python
# Block math — three supported forms:
#
#  Form A: $$ on its own line, content on next lines, $$ on its own line
#    $$
#    content
#    $$
#
#  Form B: everything on one line  $$content$$
#
#  Form C: $$ opens with content on same line, closes at end of last line
#    $$\begin{align}
#    ...
#    \end{align}$$
#
# Python regex requires distinct named groups across alternatives.
_BLOCK_MATH_PATTERN = (
    r"^ {0,3}\$\$[ \t]*\n(?P<math_text>[\s\S]+?)\n\$\$[ \t]*$"
    r"|^ {0,3}\$\$[ \t]*(?P<math_text_s>[^\n$][^\n]*?)[ \t]*\$\$[ \t]*$"
    r"|^ {0,3}\$\$(?P<math_text_m>[^\n$][^\n]*\n[\s\S]+?)\$\$[ \t]*$"
)
```

**Step 2: Update `_parse_block_math` to read `math_text_m`**

Find:
```python
def _parse_block_math(block: BlockParser, m: Any, state: BlockState) -> int:
    math_text: str = m.group("math_text") or m.group("math_text_s") or ""
```

Replace with:
```python
def _parse_block_math(block: BlockParser, m: Any, state: BlockState) -> int:
    math_text: str = (
        m.group("math_text") or m.group("math_text_s") or m.group("math_text_m") or ""
    )
```

**Step 3: Run the four new tests**

```bash
uv run pytest tests/adapters/channels/test_markdown_plugins.py::TestMatrixMathPlugin -v
```

Expected: all four new tests pass; all pre-existing `TestMatrixMathPlugin` tests pass.

**Step 4: Run full suite and linters**

```bash
uv run pytest tests/ -q --tb=short
uv run ruff check .
uv run ruff format . --check
uv run mypy squidbot/
```

Expected: 631 + 4 = 635 tests pass, no lint/type errors.

**Step 5: Commit**

```bash
git add squidbot/adapters/channels/matrix_markdown.py
git commit -m "fix: support inline-open block math (\$\$content\\n...\\n...content\$\$)"
```

---

## Task 3: Failing tests — backtick inline math

**Files:**
- Test: `tests/adapters/channels/test_markdown_plugins.py`

**Step 1: Add failing tests inside `TestMatrixMathPlugin`**

```python
def test_inline_math_backtick_form(self) -> None:
    r"""$`expr`$ renders as span with data-mx-maths."""
    result = _matrix_md(r"Energy: $`E = mc^2`$")
    assert '<span data-mx-maths="E = mc^2">' in result

def test_inline_math_backtick_pipe_expression(self) -> None:
    r"""$`a | b`$ works for expressions containing pipe characters."""
    result = _matrix_md(r"$`a | b`$")
    assert '<span data-mx-maths="a | b">' in result

def test_inline_math_backtick_does_not_affect_plain_code(self) -> None:
    """`code` remains a code span; no math interpretation."""
    result = _matrix_md("`code`")
    assert "<code>code</code>" in result
    assert "data-mx-maths" not in result

def test_inline_math_backtick_no_stray_backticks(self) -> None:
    r"""$`expr`$ leaves no stray backticks in output."""
    result = _matrix_md(r"$`x^2`$")
    # The backtick delimiters must not appear in rendered output
    assert "$`" not in result
    assert "`$" not in result
```

**Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/adapters/channels/test_markdown_plugins.py::TestMatrixMathPlugin::test_inline_math_backtick_form -v
```

Expected: FAIL — no `data-mx-maths` in result.

**Step 3: Commit the failing tests**

```bash
git add tests/adapters/channels/test_markdown_plugins.py
git commit -m "test: add failing tests for backtick inline math (\$\`...\`\$)"
```

---

## Task 4: Implement — backtick inline math

**Files:**
- Modify: `squidbot/adapters/channels/matrix_markdown.py`

**Step 1: Extend `_INLINE_MATH_PATTERN`**

Find:
```python
_INLINE_MATH_PATTERN = r"\$(?!\s)(?P<math_text>.+?)(?!\s)\$"
```

Replace with (backtick form first so it takes priority in alternation):
```python
# Inline math — two supported forms:
#
#  Backtick form (GFM):  $`expr`$   — preferred when expr contains | or _
#  Standard dollar form: $expr$
#
# Backtick form is listed first so the alternation prefers it over the dollar
# form when input starts with $`.  Content must not contain backticks.
_INLINE_MATH_PATTERN = (
    r"\$`(?P<math_text_bt>[^`]+?)`\$"
    r"|\$(?!\s)(?P<math_text>.+?)(?!\s)\$"
)
```

**Step 2: Update `_parse_inline_math` to read `math_text_bt`**

Find:
```python
def _parse_inline_math(inline: InlineParser, m: Any, state: InlineState) -> int:
    state.append_token({"type": "mx_inline_math", "raw": m.group("math_text")})
    return int(m.end())
```

Replace with:
```python
def _parse_inline_math(inline: InlineParser, m: Any, state: InlineState) -> int:
    math_text: str = m.group("math_text_bt") or m.group("math_text") or ""
    state.append_token({"type": "mx_inline_math", "raw": math_text})
    return int(m.end())
```

**Step 3: Change inline registration to `before="codespan"`**

Find:
```python
md.inline.register("mx_inline_math", _INLINE_MATH_PATTERN, _parse_inline_math, before="link")
```

Replace with:
```python
md.inline.register("mx_inline_math", _INLINE_MATH_PATTERN, _parse_inline_math, before="codespan")
```

This ensures the backtick math pattern is tested before mistune's `codespan` rule
consumes the opening backtick.

**Step 4: Run the four new tests**

```bash
uv run pytest tests/adapters/channels/test_markdown_plugins.py::TestMatrixMathPlugin -v
```

Expected: all new backtick tests pass; all pre-existing tests pass.

**Step 5: Run full suite and linters**

```bash
uv run pytest tests/ -q --tb=short
uv run ruff check .
uv run ruff format . --check
uv run mypy squidbot/
```

Expected: all tests pass, no lint/type errors.

**Step 6: Commit**

```bash
git add squidbot/adapters/channels/matrix_markdown.py
git commit -m "feat: add backtick inline math syntax (\$\`...\`\$)"
```

---

## Task 5: Failing tests — fenced block math

**Files:**
- Test: `tests/adapters/channels/test_markdown_plugins.py`

**Step 1: Add failing tests inside `TestMatrixMathPlugin`**

```python
def test_block_math_fenced_backtick(self) -> None:
    """```math fence renders as div with data-mx-maths."""
    src = "```math\nE = mc^2\n```"
    result = _matrix_md(src)
    assert '<div data-mx-maths="E = mc^2">' in result

def test_block_math_fenced_multiline(self) -> None:
    """Multi-line ```math fence preserves all content lines."""
    src = "```math\n\\frac{a}{b}\n= c\n```"
    result = _matrix_md(src)
    assert "\\frac{a}{b}" in result
    assert '<div data-mx-maths="' in result

def test_block_math_fenced_tilde(self) -> None:
    """~~~math tilde fence also renders as div with data-mx-maths."""
    src = "~~~math\nE = mc^2\n~~~"
    result = _matrix_md(src)
    assert '<div data-mx-maths="E = mc^2">' in result

def test_block_math_fenced_no_interference_with_code(self) -> None:
    """```python fence is unaffected — renders as code block, not math."""
    src = "```python\nprint('hello')\n```"
    result = _matrix_md(src)
    assert "data-mx-maths" not in result
    assert "language-python" in result
```

**Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/adapters/channels/test_markdown_plugins.py::TestMatrixMathPlugin::test_block_math_fenced_backtick -v
```

Expected: FAIL — `data-mx-maths` absent; content appears in `<pre><code>` block.

**Step 3: Commit the failing tests**

```bash
git add tests/adapters/channels/test_markdown_plugins.py
git commit -m "test: add failing tests for fenced block math (\`\`\`math)"
```

---

## Task 6: Implement — fenced block math

**Files:**
- Modify: `squidbot/adapters/channels/matrix_markdown.py`

**Step 1: Add `_BLOCK_MATH_FENCE_PATTERN` constant**

Add this constant directly below `_BLOCK_MATH_PATTERN` and before `_INLINE_MATH_PATTERN`:

```python
# Fenced block math: ```math or ~~~math code fence.
# Registered before mistune's fenced_code rule so we intercept first.
# Both backtick and tilde fences are accepted.
_BLOCK_MATH_FENCE_PATTERN = (
    r"^ {0,3}(?:```|~~~)[ \t]*math[ \t]*\n"
    r"(?P<math_text_f>[\s\S]+?)"
    r"\n {0,3}(?:```|~~~)[ \t]*$"
)
```

**Step 2: Add `_parse_fenced_math` inside `plugin_mx_math`**

Add this function immediately after `_parse_block_math` inside `plugin_mx_math`:

```python
def _parse_fenced_math(block: BlockParser, m: Any, state: BlockState) -> int:
    math_text: str = m.group("math_text_f") or ""
    # Emit mx_block_math tokens so the existing renderer is reused.
    state.append_token({"type": "mx_block_math", "raw": math_text})
    return int(m.end()) + 1
```

**Step 3: Register the new fenced rule**

Find the registration block near the end of `plugin_mx_math`:
```python
md.block.register("mx_block_math", _BLOCK_MATH_PATTERN, _parse_block_math, before="list")
```

Add the fenced rule registration directly after it:
```python
md.block.register(
    "mx_fenced_math", _BLOCK_MATH_FENCE_PATTERN, _parse_fenced_math, before="fenced_code"
)
```

No renderer registration is needed — `_parse_fenced_math` emits `mx_block_math`
tokens which already have `_render_block_math` registered.

**Step 4: Run the four new tests**

```bash
uv run pytest tests/adapters/channels/test_markdown_plugins.py::TestMatrixMathPlugin -v
```

Expected: all new fenced tests pass; all pre-existing tests pass.

**Step 5: Run full suite and linters**

```bash
uv run pytest tests/ -q --tb=short
uv run ruff check .
uv run ruff format . --check
uv run mypy squidbot/
```

Expected: all tests pass (635 + 4 new = 639 base; + however many pre-existing),
no lint/type errors.

**Step 6: Commit**

```bash
git add squidbot/adapters/channels/matrix_markdown.py
git commit -m "feat: add fenced block math syntax (\`\`\`math)"
```

---

## Task 7: Update module docstring

**Files:**
- Modify: `squidbot/adapters/channels/matrix_markdown.py`

**Step 1: Update the module-level docstring**

Find the module docstring at the top of `matrix_markdown.py`.  Replace the `plugin_mx_math` bullet with:

```text
- plugin_mx_math: mistune plugin that converts LaTeX math syntax to the Matrix
  spec v1.11+ data-mx-maths format.  Supported syntaxes:
    · $...$          standard inline math
    · $`...`$        GFM backtick inline math
    · $$...$$        block math (delimiter on own line, single-line, or inline-open)
    · ```math        GFM fenced block math (backtick or tilde fence)
```

**Step 2: Run linters to confirm no issues**

```bash
uv run ruff check .
uv run mypy squidbot/
```

**Step 3: Commit**

```bash
git add squidbot/adapters/channels/matrix_markdown.py
git commit -m "docs: update matrix_markdown module docstring for new math syntaxes"
```

---

## Task 8: Final verification

**Step 1: Run complete test suite**

```bash
uv run pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests pass, zero failures.

**Step 2: Run all linters**

```bash
uv run ruff check . && uv run ruff format . --check && uv run mypy squidbot/
```

Expected: no errors.

**Step 3: Push and open PR**

```bash
git push -u origin feat/gfm-math-syntax
gh pr create \
  --title "feat: add GFM math syntax (backtick inline, fenced block, inline-open block)" \
  --body "$(cat <<'EOF'
## Summary

- Fixes block math rendering for `$$\begin{env}...\end{env}$$` (inline-open form) — the three failing equations reported in the original bug
- Adds GFM backtick inline math `` $`expr`$ ``
- Adds GFM fenced block math ` ```math ` (backtick and tilde fences)

## Changes

- `squidbot/adapters/channels/matrix_markdown.py`: extend `_BLOCK_MATH_PATTERN` with Form C alternative; extend `_INLINE_MATH_PATTERN` with backtick form; add `_BLOCK_MATH_FENCE_PATTERN` and `_parse_fenced_math`; change inline registration to `before="codespan"`
- `tests/adapters/channels/test_markdown_plugins.py`: ~12 new test cases

## Testing

All existing 631 tests pass plus 12 new tests covering each new syntax variant and regression scenarios.
EOF
)"
```
