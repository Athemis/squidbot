"""Tests for mistune plugin rendering in Matrix and Email channels.

This module provides comprehensive test coverage for all enabled mistune plugins
(table, strikethrough, task_lists, url, footnotes, superscript, subscript) to ensure
correct Markdown-to-HTML conversion. Tests verify plugin behavior in isolation and
validate that both Matrix and Email channel adapters properly render extended Markdown
syntax. These tests serve as unit-level verification of the markdown rendering pipeline.
"""

from __future__ import annotations


class TestTablePlugin:
    """Test table plugin renders Markdown tables to HTML.

    Tests verify that the mistune table plugin correctly converts Markdown
    table syntax to HTML table elements with proper structure and alignment.
    """

    def test_simple_table_renders_to_html(self) -> None:
        """Test simple table renders to HTML with thead and tbody.

        Returns:
            None
        """
        from squidbot.adapters.channels.matrix import _render_markdown

        md = """| Header 1 | Header 2 |
|----------|----------|
| Cell 1   | Cell 2   |
| Cell 3   | Cell 4   |"""
        result = _render_markdown(md)
        assert "<table>" in result
        assert "<thead>" in result
        assert "<tbody>" in result
        assert "<th>Header 1</th>" in result
        assert "<td>Cell 1</td>" in result

    def test_table_with_alignment(self) -> None:
        """Test table with column alignment preserves alignment in HTML.

        Returns:
            None
        """
        from squidbot.adapters.channels.matrix import _render_markdown

        md = """| Left | Center | Right |
|:-----|:------:|------:|
| L1   | C1     | R1    |"""
        result = _render_markdown(md)
        assert "<table>" in result
        assert 'style="text-align:left"' in result or 'align="left"' in result

    def test_table_in_email_channel(self) -> None:
        """Test Email channel _md renders tables correctly.

        Returns:
            None
        """
        from squidbot.adapters.channels.email import _md

        md = """| A | B |
|---|---|
| 1 | 2 |"""
        result = _md(md)
        assert isinstance(result, str)
        assert "<table>" in result


class TestStrikethroughPlugin:
    """Test strikethrough plugin renders ~~text~~ to HTML del tags.

    Tests verify that the mistune strikethrough plugin correctly converts
    Markdown strikethrough syntax to HTML del elements.
    """

    def test_strikethrough_renders_to_del_tag(self) -> None:
        """Test strikethrough renders to del tag.

        Returns:
            None
        """
        """Double tilde renders as <del> tag."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("This is ~~deleted~~ text")
        assert "<del>deleted</del>" in result

    def test_multiple_strikethroughs(self) -> None:
        """Multiple strikethrough sections all render correctly."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("~~old~~ new ~~obsolete~~")
        assert "<del>old</del>" in result
        assert "<del>obsolete</del>" in result

    def test_strikethrough_in_email(self) -> None:
        """Email channel _md renders strikethrough."""
        from squidbot.adapters.channels.email import _md

        result = _md("~~strikethrough~~")
        assert "<del>strikethrough</del>" in result


class TestTaskListsPlugin:
    """Test task_lists plugin renders task lists with checkboxes."""

    def test_unchecked_task_renders_checkbox(self) -> None:
        """Unchecked task [ ] renders with checkbox input."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("- [ ] Incomplete task")
        assert 'type="checkbox"' in result
        assert "checked" not in result
        assert "disabled" in result

    def test_checked_task_renders_checked_checkbox(self) -> None:
        """Checked task [x] renders with checked checkbox."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("- [x] Completed task")
        assert 'type="checkbox"' in result
        assert "checked" in result

    def test_mixed_task_list(self) -> None:
        """Mixed completed and incomplete tasks render correctly."""
        from squidbot.adapters.channels.matrix import _render_markdown

        md = """- [x] Done
- [ ] Todo
- [x] Also done"""
        result = _render_markdown(md)
        assert result.count("checked") >= 2

    def test_task_list_in_email(self) -> None:
        """Email channel _md renders task lists."""
        from squidbot.adapters.channels.email import _md

        result = _md("- [x] Task")
        assert 'type="checkbox"' in result


class TestUrlPlugin:
    """Test url plugin auto-links bare URLs."""

    def test_auto_link_http_url(self) -> None:
        """Bare HTTP URL converts to anchor tag."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("Visit https://example.com for more")
        assert '<a href="https://example.com"' in result

    def test_auto_link_www_url(self) -> None:
        """Bare www URL does not auto-link (url plugin requires scheme)."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("Check www.example.com")
        assert "<a" not in result
        assert "www.example.com" in result

    def test_url_in_email(self) -> None:
        """Email channel _md auto-links URLs."""
        from squidbot.adapters.channels.email import _md

        result = _md("Go to https://test.org")
        assert '<a href="https://test.org"' in result


class TestFootnotesPlugin:
    """Test footnotes plugin renders footnote references and definitions."""

    def test_footnote_reference_and_definition(self) -> None:
        """Footnote reference [^1] and definition render to HTML."""
        from squidbot.adapters.channels.matrix import _render_markdown

        md = """This has a footnote[^1].

[^1]: This is the footnote content."""
        result = _render_markdown(md)
        assert "footnote-ref" in result or 'id="fnref:' in result
        assert "footnote" in result.lower()

    def test_multiple_footnotes(self) -> None:
        """Multiple footnotes render with correct numbering."""
        from squidbot.adapters.channels.matrix import _render_markdown

        md = """First[^1] and second[^2].

[^1]: First note.
[^2]: Second note."""
        result = _render_markdown(md)
        assert result.count("footnote") >= 2

    def test_footnotes_in_email(self) -> None:
        """Email channel _md renders footnotes."""
        from squidbot.adapters.channels.email import _md

        md = "Text[^1].\n\n[^1]: Note."
        result = _md(md)
        assert "footnote" in result.lower()


class TestSuperscriptPlugin:
    """Test superscript plugin renders ^text^ to <sup>."""

    def test_superscript_renders_to_sup_tag(self) -> None:
        """Caret-wrapped text renders as <sup> tag."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("E=mc^2^")
        assert "<sup>2</sup>" in result

    def test_superscript_in_formula(self) -> None:
        """Superscript in mathematical formula renders correctly."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("x^n^ + y^m^")
        assert "<sup>n</sup>" in result
        assert "<sup>m</sup>" in result

    def test_superscript_in_email(self) -> None:
        """Email channel _md renders superscript."""
        from squidbot.adapters.channels.email import _md

        result = _md("10^2^")
        assert "<sup>2</sup>" in result


class TestSubscriptPlugin:
    """Test subscript plugin renders ~text~ to <sub>."""

    def test_subscript_renders_to_sub_tag(self) -> None:
        """Tilde-wrapped text renders as <sub> tag."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("H~2~O")
        assert "<sub>2</sub>" in result

    def test_subscript_in_chemical_formula(self) -> None:
        """Subscript in chemical formula renders correctly."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("CO~2~ and CH~4~")
        assert "<sub>2</sub>" in result
        assert "<sub>4</sub>" in result

    def test_subscript_in_email(self) -> None:
        """Email channel _md renders subscript."""
        from squidbot.adapters.channels.email import _md

        result = _md("H~2~O")
        assert "<sub>2</sub>" in result


class TestAllPluginsIntegration:
    """Test that all plugins work together in both channels."""

    def test_matrix_uses_all_plugins(self) -> None:
        """Matrix _render_markdown renders content using all 7 plugins."""
        from squidbot.adapters.channels.matrix import _render_markdown

        md = """# Document

| Feature | Status |
|---------|--------|
| Table   | ~~old~~ |
| Plugin  | active |

- [x] Done
- [ ] Todo

See https://example.com for details[^1].

Formula: E=mc^2^, H~2~O.

[^1]: Reference URL.
"""
        result = _render_markdown(md)

        # Table
        assert "<table>" in result
        # Strikethrough
        assert "<del>old</del>" in result
        # Task list
        assert 'type="checkbox"' in result
        # URL
        assert '<a href="https://example.com"' in result
        # Footnote
        assert "footnote" in result.lower()
        # Superscript
        assert "<sup>2</sup>" in result
        # Subscript
        assert "<sub>2</sub>" in result

    def test_email_uses_all_plugins(self) -> None:
        """Email _md renders content using all 7 plugins."""
        from squidbot.adapters.channels.email import _md

        md = """Summary

| Item | Value |
|------|-------|
| A    | ~~1~~ |
| B    | 2     |

- [x] Checked
- [ ] Unchecked

Link: https://test.org for more[^note].

Math: x^n^, H~2~O.

[^note]: Footnote text.
"""
        result = _md(md)

        # Table
        assert "<table>" in result
        # Strikethrough
        assert "<del>1</del>" in result
        # Task list
        assert 'type="checkbox"' in result
        # URL
        assert '<a href="https://test.org"' in result
        # Footnote
        assert "footnote" in result.lower()
        # Superscript
        assert "<sup>n</sup>" in result
        # Subscript
        assert "<sub>2</sub>" in result

    def test_matrix_render_returns_string(self) -> None:
        """_render_markdown always returns a string."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("Any **markdown** here")
        assert isinstance(result, str)

    def test_email_md_returns_string(self) -> None:
        """_md always returns a string."""
        from squidbot.adapters.channels.email import _md

        result = _md("Any **markdown** here")
        assert isinstance(result, str)
