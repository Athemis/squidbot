# Markdown Plugin Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable extended Markdown rendering in Matrix and Email channels by adding mistune plugins: `table`, `strikethrough`, `task_lists`, `url`, `footnotes`, `superscript`, `subscript`.

**Architecture:** Single-line change in two channel adapters — add `plugins=[...]` to `mistune.create_markdown()` calls.

**Tech Stack:** mistune>=3.0 (already installed)

---

## Task 1: Write Unit Tests for Markdown Plugins

**Files:**
- Create: `tests/adapters/channels/test_markdown_plugins.py`

**Step 1: Write the failing test**

```python
"""Tests for Markdown plugin rendering in channel adapters."""

from __future__ import annotations

import mistune


_PLUGINS = ["table", "strikethrough", "task_lists", "url", "footnotes", "superscript", "subscript"]


class TestMistunePlugins:
    """Verify mistune plugins render correctly."""

    def test_table_plugin_renders_html_table(self) -> None:
        """Table markdown should produce HTML table elements."""
        md = mistune.create_markdown(escape=True, plugins=["table"])
        markdown_input = """| Header 1 | Header 2 |
|----------|----------|
| Cell 1   | Cell 2   |"""
        result = md(markdown_input)
        assert "<table>" in result
        assert "<thead>" in result
        assert "<th>Header 1</th>" in result
        assert "<th>Header 2</th>" in result
        assert "<tbody>" in result
        assert "<td>Cell 1</td>" in result
        assert "<td>Cell 2</td>" in result

    def test_table_with_alignment(self) -> None:
        """Table alignment should produce aligned columns."""
        md = mistune.create_markdown(escape=True, plugins=["table"])
        markdown_input = """| Left | Center | Right |
|:-----|:------:|------:|
| L1   | C1     | R1    |"""
        result = md(markdown_input)
        assert 'style="text-align:left"' in result
        assert 'style="text-align:center"' in result
        assert 'style="text-align:right"' in result

    def test_strikethrough_plugin(self) -> None:
        """Strikethrough should produce <del> tags."""
        md = mistune.create_markdown(escape=True, plugins=["strikethrough"])
        result = md("This is ~~deleted~~ text.")
        assert "<del>deleted</del>" in result

    def test_task_lists_plugin(self) -> None:
        """Task lists should produce checkbox items."""
        md = mistune.create_markdown(escape=True, plugins=["task_lists"])
        markdown_input = """- [x] Done
- [ ] Pending"""
        result = md(markdown_input)
        assert "task-list-item" in result
        assert '<input type="checkbox" checked' in result
        assert '<input type="checkbox" disabled' in result

    def test_url_plugin_auto_link(self) -> None:
        """URL plugin should auto-link bare URLs."""
        md = mistune.create_markdown(escape=True, plugins=["url"])
        result = md("Visit https://example.com for more.")
        assert '<a href="https://example.com">https://example.com</a>' in result

    def test_footnotes_plugin(self) -> None:
        """Footnotes should produce footnote links."""
        md = mistune.create_markdown(escape=True, plugins=["footnotes"])
        markdown_input = """Text with a footnote[^1].

[^1]: This is the footnote."""
        result = md(markdown_input)
        assert "footnote-ref" in result

    def test_superscript_plugin(self) -> None:
        """Superscript should produce <sup> tags."""
        md = mistune.create_markdown(escape=True, plugins=["superscript"])
        result = md("E = mc^2")
        assert "<sup>2</sup>" in result

    def test_subscript_plugin(self) -> None:
        """Subscript should produce <sub> tags."""
        md = mistune.create_markdown(escape=True, plugins=["subscript"])
        result = md("H~2~O is water.")
        assert "<sub>2</sub>" in result


class TestMatrixMarkdownRendering:
    """Test Matrix channel _render_markdown function."""

    def test_render_markdown_includes_tables(self) -> None:
        """Matrix _render_markdown should render tables to HTML."""
        from squidbot.adapters.channels.matrix import _render_markdown

        markdown_input = """| Name | Value |
|------|-------|
| Foo  | 123   |"""
        result = _render_markdown(markdown_input)
        assert "<table>" in result
        assert "<th>Name</th>" in result
        assert "<td>Foo</td>" in result

    def test_render_markdown_includes_strikethrough(self) -> None:
        """Matrix _render_markdown should render strikethrough."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("This is ~~corrected~~ text.")
        assert "<del>corrected</del>" in result

    def test_render_markdown_includes_auto_url(self) -> None:
        """Matrix _render_markdown should auto-link URLs."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("Visit https://example.com")
        assert '<a href="https://example.com"' in result

    def test_render_markdown_includes_superscript(self) -> None:
        """Matrix _render_markdown should render superscript."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("E = mc^2")
        assert "<sup>2</sup>" in result

    def test_render_markdown_includes_subscript(self) -> None:
        """Matrix _render_markdown should render subscript."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("H~2~O is water.")
        assert "<sub>2</sub>" in result


class TestEmailMarkdownRendering:
    """Test Email channel markdown rendering."""

    def test_email_markdown_includes_tables(self) -> None:
        """Email markdown renderer should render tables to HTML."""
        from squidbot.adapters.channels.email import _md

        markdown_input = """| Name | Value |
|------|-------|
| Bar  | 456   |"""
        result = _md(markdown_input)
        assert isinstance(result, str)
        assert "<table>" in result
        assert "<th>Name</th>" in result
        assert "<td>Bar</td>" in result

    def test_email_markdown_includes_strikethrough(self) -> None:
        """Email markdown renderer should render strikethrough."""
        from squidbot.adapters.channels.email import _md

        result = _md("This is ~~corrected~~ text.")
        assert isinstance(result, str)
        assert "<del>corrected</del>" in result

    def test_email_markdown_includes_auto_url(self) -> None:
        """Email markdown renderer should auto-link URLs."""
        from squidbot.adapters.channels.email import _md

        result = _md("Visit https://example.com")
        assert isinstance(result, str)
        assert '<a href="https://example.com"' in result

    def test_email_markdown_includes_superscript(self) -> None:
        """Email markdown renderer should render superscript."""
        from squidbot.adapters.channels.email import _md

        result = _md("E = mc^2")
        assert isinstance(result, str)
        assert "<sup>2</sup>" in result

    def test_email_markdown_includes_subscript(self) -> None:
        """Email markdown renderer should render subscript."""
        from squidbot.adapters.channels.email import _md

        result = _md("H~2~O is water.")
        assert isinstance(result, str)
        assert "<sub>2</sub>" in result
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/adapters/channels/test_markdown_plugins.py -v`
Expected: Tests for `_render_markdown` and email `_md` FAIL (no plugins yet)

**Step 3: Commit test file**

```bash
git add tests/adapters/channels/test_markdown_plugins.py
git commit -m "test: add failing tests for markdown plugin rendering"
```

---

## Task 2: Enable Plugins in Matrix Channel

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py:65`

**Step 1: Update mistune initialization**

Change line 65 from:
```python
_md = mistune.create_markdown(escape=True)
```

To:
```python
_md = mistune.create_markdown(
    escape=True,
    plugins=["table", "strikethrough", "task_lists", "url", "footnotes", "superscript", "subscript"],
)
```

**Step 2: Run tests to verify**

Run: `uv run pytest tests/adapters/channels/test_markdown_plugins.py::TestMatrixMarkdownRendering -v`
Expected: PASS

**Step 3: Commit**

```bash
git add squidbot/adapters/channels/matrix.py
git commit -m "feat(matrix): enable mistune plugins for extended markdown support"
```

---

## Task 3: Enable Plugins in Email Channel

**Files:**
- Modify: `squidbot/adapters/channels/email.py:44`

**Step 1: Update mistune initialization**

Change line 44 from:
```python
_md = mistune.create_markdown(escape=True)
```

To:
```python
_md = mistune.create_markdown(
    escape=True,
    plugins=["table", "strikethrough", "task_lists", "url", "footnotes", "superscript", "subscript"],
)
```

**Step 2: Run tests to verify**

Run: `uv run pytest tests/adapters/channels/test_markdown_plugins.py::TestEmailMarkdownRendering -v`
Expected: PASS

**Step 3: Commit**

```bash
git add squidbot/adapters/channels/email.py
git commit -m "feat(email): enable mistune plugins for extended markdown support"
```

---

## Task 4: Full Test Suite Verification

**Step 1: Run all plugin tests**

Run: `uv run pytest tests/adapters/channels/test_markdown_plugins.py -v`
Expected: All tests PASS

**Step 2: Run linting and type checking**

Run: `uv run ruff check . && uv run ruff format . --check && uv run mypy squidbot/`
Expected: No errors

**Step 3: Run full test suite**

Run: `uv run pytest`
Expected: All tests PASS

---

## Summary

| Task | Description | Files Changed |
|------|-------------|---------------|
| 1 | Add failing tests | `tests/adapters/channels/test_markdown_plugins.py` |
| 2 | Fix Matrix channel | `squidbot/adapters/channels/matrix.py:65` |
| 3 | Fix Email channel | `squidbot/adapters/channels/email.py:44` |
| 4 | Verify all tests pass | — |
