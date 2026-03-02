# Matrix Block Spoiler Plugin Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `plugin_mx_block_spoiler` to `matrix_markdown.py` so that `>!`-prefixed lines render as `<span data-mx-spoiler>` with inner inline Markdown support.

**Architecture:** New block-level parser rule in mistune that collects consecutive `>!`-prefixed lines, strips the prefix, renders the content via the inline renderer, and wraps it in `<span data-mx-spoiler>`. Registered `before="block_quote"` so `>!` is tested before `>`. No nh3 changes needed — `span[data-mx-spoiler]` is already in the allowlist. `matrix.py` adds `plugin_mx_block_spoiler` to its plugin list.

**Tech Stack:** `mistune` (block parser extension), `nh3` (unchanged), `pytest`

---

### Task 1: Write failing tests for `plugin_mx_block_spoiler`

**Files:**
- Modify: `tests/adapters/channels/test_markdown_plugins.py`

The existing `TestMatrixSpoilerPlugin` class already tests the inline `||text||` plugin.
Add 6 new test methods to the **same class**.

**Step 1: Add the failing tests**

Open `tests/adapters/channels/test_markdown_plugins.py` and locate `TestMatrixSpoilerPlugin`.
Add these methods after the existing 4 tests:

```python
def test_block_spoiler_single_line_renders_span(self) -> None:
    """>! single line renders to <span data-mx-spoiler>."""
    result = _render_markdown(">! hidden content")
    assert "<span data-mx-spoiler>" in result
    assert "hidden content" in result

def test_block_spoiler_multiline_renders_single_span(self) -> None:
    """Multi-line >! block produces one <span data-mx-spoiler>."""
    result = _render_markdown(">! first line\n>!\n>! second line")
    assert result.count("<span data-mx-spoiler>") == 1
    assert "first line" in result
    assert "second line" in result

def test_block_spoiler_inline_markdown_rendered(self) -> None:
    """Inline markdown inside >! block is rendered."""
    result = _render_markdown(">! **bold** and _italic_")
    assert "<span data-mx-spoiler>" in result
    assert "<strong>bold</strong>" in result

def test_block_spoiler_does_not_appear_in_email(self) -> None:
    """>! lines are NOT rendered as spoiler in email channel."""
    result = _md(">! hidden")
    assert "data-mx-spoiler" not in result

def test_block_spoiler_coexists_with_inline_spoiler(self) -> None:
    """Block and inline spoiler both work in the same message."""
    result = _render_markdown(">! block spoiler\n\n||inline spoiler||")
    assert result.count("data-mx-spoiler") >= 2

def test_block_spoiler_does_not_break_blockquote(self) -> None:
    """> blockquote still works alongside >! spoiler."""
    result = _render_markdown("> normal quote")
    assert "<blockquote>" in result
    assert "data-mx-spoiler" not in result
```

**Step 2: Run to confirm all 6 fail**

```bash
uv run pytest tests/adapters/channels/test_markdown_plugins.py::TestMatrixSpoilerPlugin -v
```

Expected: 6 new tests FAIL (NameError or AssertionError), 4 existing pass.

**Step 3: Commit the failing tests**

```bash
git add tests/adapters/channels/test_markdown_plugins.py
git commit -m "test: add failing tests for Matrix block spoiler plugin (>! syntax)"
```

---

### Task 2: Implement `plugin_mx_block_spoiler` in `matrix_markdown.py`

**Files:**
- Modify: `squidbot/adapters/channels/matrix_markdown.py`

**Step 1: Add the block pattern constant after the inline spoiler pattern (line ~80)**

```python
_BLOCK_SPOILER_PATTERN = r"(?:^>![ \t]?[^\n]*(?:\n|$))+"
```

This matches one or more consecutive lines starting with `>!` (optionally followed by a space/tab and content).

**Step 2: Add `plugin_mx_block_spoiler` function after `plugin_mx_spoiler`**

```python
def plugin_mx_block_spoiler(md: Markdown) -> None:
    """Mistune plugin that renders >!-prefixed lines to Matrix data-mx-spoiler format.

    Block spoiler syntax (one or more lines starting with '>!') becomes
    <span data-mx-spoiler>rendered inline content</span>.
    Inner text is rendered as inline Markdown so **bold**, _italic_ etc. work.
    Registered before 'block_quote' so '>!' is tested before '>'.

    Args:
        md: The Markdown instance to extend.
    """

    def _parse_block_spoiler(block: BlockParser, m: Any, state: BlockState) -> int:
        raw = m.group(0)
        # Strip the '>!' prefix (and optional single space) from each line.
        lines = []
        for line in raw.splitlines():
            if line.startswith(">! "):
                lines.append(line[3:])
            elif line.startswith(">!\t"):
                lines.append(line[3:])
            elif line.rstrip() == ">!":
                lines.append("")
            else:
                lines.append(line)
        state.append_token({"type": "mx_block_spoiler", "raw": "\n".join(lines)})
        return int(m.end())

    def _render_block_spoiler(renderer: BaseRenderer, text: str) -> str:
        return f"<span data-mx-spoiler>{text}</span>\n"

    md.block.register(
        "mx_block_spoiler", _BLOCK_SPOILER_PATTERN, _parse_block_spoiler, before="block_quote"
    )
    if md.renderer and md.renderer.NAME == "html":
        md.renderer.register("mx_block_spoiler", _render_block_spoiler)
```

**Note on inline rendering:** mistune renders block tokens with `raw` content by passing it
through the inline parser automatically when the token has a `raw` key and `children` is absent.
If that does not apply for custom block tokens, the parse function must produce `children` instead:

```python
# Alternative if 'raw' is not auto-rendered as inline:
new_state = state.copy()  # BlockState has no copy(); use InlineState approach instead
```

Because block parser state differs from inline state, the safest approach is to store `raw`
and let the renderer receive it as `text` (mistune calls `render_token` which passes `raw`
as the `text` argument for single-string tokens). Test to confirm; if `text` arrives
pre-rendered as inline HTML, the renderer is correct as-is. If `text` arrives as plain source,
the renderer needs to call `md.inline(text)` — but the renderer does not have access to `md`.

**Pragmatic resolution:** mistune's built-in block tokens with `raw` content (e.g. `block_code`)
receive the raw string as `text` in the renderer. Inline rendering of block content happens via
`children` tokens, not `raw`. So to get inline rendering, store as `children`:

```python
def _parse_block_spoiler(block: BlockParser, m: Any, state: BlockState) -> int:
    raw = m.group(0)
    lines = []
    for line in raw.splitlines():
        if line.startswith(">! "):
            lines.append(line[3:])
        elif line.startswith(">!\t"):
            lines.append(line[3:])
        elif line.rstrip() == ">!":
            lines.append("")
        else:
            lines.append(line)
    content = "\n".join(lines)
    # Render inline markdown now using the inline parser attached to the block parser.
    children = block.state.copy()  # won't work — use md reference instead
    state.append_token({"type": "mx_block_spoiler", "raw": content, "children": []})
    return int(m.end())
```

**Simplest correct approach:** render inline content inside the parse function using
`block.md.inline` (the inline parser is accessible via `block.md`):

```python
def _parse_block_spoiler(block: BlockParser, m: Any, state: BlockState) -> int:
    raw = m.group(0)
    lines = []
    for line in raw.splitlines():
        if line.startswith(">! "):
            lines.append(line[3:])
        elif line.startswith(">!\t"):
            lines.append(line[3:])
        elif line.rstrip() == ">!":
            lines.append("")
        else:
            lines.append(line)
    content = "\n".join(lines)
    # Render inline markdown using the same inline parser as the rest of the document.
    inline_state = block.md.inline.new_state()  # type: ignore[attr-defined]
    inline_state.src = content
    rendered = block.md.inline.render(inline_state)  # type: ignore[attr-defined]
    state.append_token({"type": "mx_block_spoiler", "children": rendered})
    return int(m.end())

def _render_block_spoiler(renderer: BaseRenderer, text: str) -> str:
    return f"<span data-mx-spoiler>{text}</span>\n"
```

`block.md` is the parent `Markdown` instance — accessible in mistune's block parser callbacks
because `BlockParser` stores `self.md` after `md.block = self` assignment in `create_markdown`.
The `type: ignore` suppresses mypy's complaint about the dynamic attribute.

**Step 2: Update `__all__`**

```python
__all__ = ["plugin_mx_math", "plugin_mx_spoiler", "plugin_mx_block_spoiler", "sanitize_for_matrix"]
```

**Step 3: Run the new tests**

```bash
uv run pytest tests/adapters/channels/test_markdown_plugins.py::TestMatrixSpoilerPlugin -v
```

Expected: all 10 pass. If inline rendering produces plain text instead of HTML, revisit the
`block.md.inline` approach or fall back to a simpler renderer that trusts mistune's `children`
pipeline.

---

### Task 3: Wire `plugin_mx_block_spoiler` into `matrix.py`

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`

**Step 1: Update the import**

```python
from squidbot.adapters.channels.matrix_markdown import (
    plugin_mx_math,
    plugin_mx_spoiler,
    plugin_mx_block_spoiler,
    sanitize_for_matrix,
)
```

**Step 2: Add to `create_markdown` call (line ~71)**

```python
_md = mistune.create_markdown(
    escape=False,
    plugins=[*MARKDOWN_PLUGINS, plugin_mx_math, plugin_mx_spoiler, plugin_mx_block_spoiler],
)
```

**Step 3: Run full test suite**

```bash
uv run pytest tests/adapters/channels/test_markdown_plugins.py -v
```

Expected: all 54 tests pass (48 existing + 6 new).

---

### Task 4: Lint, type-check, full suite, commit

**Step 1: Lint and format check**

```bash
uv run ruff check . && uv run ruff format . --check
```

Expected: no errors.

**Step 2: Type check**

```bash
uv run mypy squidbot/
```

Expected: `Success: no issues found in 46 source files`.
If `block.md` causes `attr-defined` errors, use `# type: ignore[attr-defined]` on those lines.

**Step 3: Full test suite**

```bash
uv run pytest
```

Expected: all tests pass.

**Step 4: Commit**

```bash
git add squidbot/adapters/channels/matrix_markdown.py squidbot/adapters/channels/matrix.py
git commit -m "feat: add block spoiler plugin (>! syntax) for Matrix"
```

---

### Task 5: Update docs and push

**Step 1: Commit implementation plan**

```bash
git add docs/plans/2026-03-02-matrix-block-spoiler-implementation-plan.md
git commit -m "docs: add Matrix block spoiler implementation plan"
```

**Step 2: Push and update PR**

```bash
git push
```

The existing PR #54 (`feat/markdown-rendering`) will automatically include the new commits.
