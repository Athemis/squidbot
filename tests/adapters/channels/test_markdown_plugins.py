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
        """Test table with column alignment renders table structure.

        Note: Matrix spec v1.17 does not permit style= attributes, so nh3
        strips alignment styles. The table structure is preserved.

        Returns:
            None
        """
        from squidbot.adapters.channels.matrix import _render_markdown

        md = """| Left | Center | Right |
|:-----|:------:|------:|
| L1   | C1     | R1    |"""
        result = _render_markdown(md)
        assert "<table>" in result
        assert "<th>Left</th>" in result

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

    def test_unchecked_task_renders_list_item(self) -> None:
        """Unchecked task [ ] renders as a list item in Matrix.

        Note: <input> is not in the Matrix spec v1.17 allowed tags, so nh3
        strips the checkbox. Task lists are still parsed but render as plain
        <ul><li> without checkboxes in the Matrix formatted_body.
        """
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("- [ ] Incomplete task")
        assert "<li>" in result
        assert "Incomplete task" in result

    def test_checked_task_renders_list_item(self) -> None:
        """Checked task [x] renders as a list item in Matrix."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("- [x] Completed task")
        assert "<li>" in result
        assert "Completed task" in result

    def test_mixed_task_list(self) -> None:
        """Mixed tasks all render as list items in Matrix."""
        from squidbot.adapters.channels.matrix import _render_markdown

        md = """- [x] Done
- [ ] Todo
- [x] Also done"""
        result = _render_markdown(md)
        assert result.count("<li>") == 3

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
        """Footnote reference [^1] renders as <sup><a> with fragment href.

        Note: nh3 strips class= and id= attributes (not in Matrix spec v1.17
        allowlist), but the <sup> and <a href="#fn-..."> structure is preserved.
        """
        from squidbot.adapters.channels.matrix import _render_markdown

        md = """This has a footnote[^1].

[^1]: This is the footnote content."""
        result = _render_markdown(md)
        assert "<sup>" in result
        assert 'href="#fn-' in result

    def test_multiple_footnotes(self) -> None:
        """Multiple footnotes each render a <sup> reference."""
        from squidbot.adapters.channels.matrix import _render_markdown

        md = """First[^1] and second[^2].

[^1]: First note.
[^2]: Second note."""
        result = _render_markdown(md)
        assert result.count("<sup>") >= 2

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
        # Task list (checkboxes stripped by nh3 — <input> not in Matrix spec v1.17)
        assert "<li>" in result
        # URL
        assert '<a href="https://example.com"' in result
        # Footnote (class/id stripped by nh3, but <sup> and href structure preserved)
        assert "<sup>" in result
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


class TestMatrixSpoilerPlugin:
    """Test Matrix-specific spoiler plugin renders ||text|| to data-mx-spoiler."""

    def test_inline_spoiler_renders_span_data_mx_spoiler(self) -> None:
        """||text|| renders to a <span> with data-mx-spoiler attribute."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("Here is ||a spoiler|| for you.")
        # nh3 normalises valueless attributes to attr="", both forms are valid HTML5
        assert "data-mx-spoiler" in result
        assert "a spoiler" in result

    def test_spoiler_preserves_inner_markdown(self) -> None:
        """Nested inline markdown inside spoiler is rendered."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("||**bold spoiler**||")
        assert "data-mx-spoiler" in result
        assert "<strong>bold spoiler</strong>" in result

    def test_spoiler_does_not_appear_in_email(self) -> None:
        """Email _md does NOT render data-mx-spoiler (Matrix-only plugin)."""
        from squidbot.adapters.channels.email import _md

        result = _md("||spoiler||")
        assert "data-mx-spoiler" not in result

    def test_spoiler_coexists_with_other_markdown(self) -> None:
        """Spoiler and standard markdown plugins work together."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("||secret: **bold**|| and ~~old~~")
        assert "data-mx-spoiler" in result
        assert "<strong>bold</strong>" in result
        assert "<del>old</del>" in result

    def test_block_spoiler_single_line_renders_span(self) -> None:
        """>! single line renders to <span data-mx-spoiler>.

        nh3 normalises valueless attributes to attr="", both forms are valid HTML5.
        """
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown(">! hidden content")
        assert "data-mx-spoiler" in result
        assert "hidden content" in result

    def test_block_spoiler_multiline_renders_single_span(self) -> None:
        """Multi-line >! block produces one <span data-mx-spoiler>.

        nh3 normalises valueless attributes to attr="", both forms are valid HTML5.
        """
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown(">! first line\n>!\n>! second line")
        assert result.count("data-mx-spoiler") == 1
        assert "first line" in result
        assert "second line" in result

    def test_block_spoiler_inline_markdown_rendered(self) -> None:
        """Inline markdown inside >! block is rendered.

        nh3 normalises valueless attributes to attr="", both forms are valid HTML5.
        """
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown(">! **bold** and _italic_")
        assert "data-mx-spoiler" in result
        assert "<strong>bold</strong>" in result
        assert "<em>italic</em>" in result

    def test_block_spoiler_does_not_appear_in_email(self) -> None:
        """>! lines are NOT rendered as spoiler in email channel."""
        from squidbot.adapters.channels.email import _md

        result = _md(">! hidden")
        assert "data-mx-spoiler" not in result
        assert "hidden" in result

    def test_block_spoiler_coexists_with_inline_spoiler(self) -> None:
        """Block and inline spoiler both work in the same message."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown(">! block spoiler\n\n||inline spoiler||")
        assert result.count("data-mx-spoiler") >= 2

    def test_block_spoiler_does_not_break_blockquote(self) -> None:
        """> blockquote still works alongside >! spoiler."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("> normal quote")
        assert "<blockquote>" in result
        assert "data-mx-spoiler" not in result

    def test_block_spoiler_no_separator_still_works(self) -> None:
        """>!content with no space separator is still recognized."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown(">!hidden")
        assert "data-mx-spoiler" in result
        assert "hidden" in result
        assert ">!" not in result


class TestSanitizeForMatrix:
    """Test nh3-based HTML sanitizer enforces Matrix spec v1.17 allowlist.

    Tests verify that sanitize_for_matrix() allows spec-permitted tags and
    attributes while stripping anything not in the Matrix v1.17 allowlist.
    """

    def test_unknown_tag_stripped_content_kept(self) -> None:
        """Unknown tags are stripped; their text content is preserved."""
        from squidbot.adapters.channels.matrix_markdown import sanitize_for_matrix

        result = sanitize_for_matrix("<mark>highlighted</mark>")
        assert "<mark>" not in result
        assert "highlighted" in result

    def test_script_tag_and_content_removed(self) -> None:
        """<script> tag and its content are fully removed."""
        from squidbot.adapters.channels.matrix_markdown import sanitize_for_matrix

        result = sanitize_for_matrix("<script>evil()</script>safe text")
        assert "evil" not in result
        assert "safe text" in result

    def test_details_summary_pass_through(self) -> None:
        """<details> and <summary> are permitted and pass through."""
        from squidbot.adapters.channels.matrix_markdown import sanitize_for_matrix

        html = "<details><summary>Title</summary><p>Body</p></details>"
        result = sanitize_for_matrix(html)
        assert "<details>" in result
        assert "<summary>Title</summary>" in result

    def test_u_tag_passes_through(self) -> None:
        """<u> is a permitted tag and passes through."""
        from squidbot.adapters.channels.matrix_markdown import sanitize_for_matrix

        result = sanitize_for_matrix("<u>underlined</u>")
        assert "<u>underlined</u>" in result

    def test_span_data_mx_spoiler_passes(self) -> None:
        """<span data-mx-spoiler> is permitted and passes through."""
        from squidbot.adapters.channels.matrix_markdown import sanitize_for_matrix

        result = sanitize_for_matrix("<span data-mx-spoiler>hidden</span>")
        assert "data-mx-spoiler" in result
        assert "hidden" in result

    def test_span_data_mx_maths_is_stripped(self) -> None:
        """data-mx-maths is not permitted once Matrix math plugin is removed."""
        from squidbot.adapters.channels.matrix_markdown import sanitize_for_matrix

        result = sanitize_for_matrix('<span data-mx-maths="x^2"><code>x^2</code></span>')
        assert "data-mx-maths" not in result

    def test_code_class_language_passes(self) -> None:
        """code[class=language-python] is permitted."""
        from squidbot.adapters.channels.matrix_markdown import sanitize_for_matrix

        result = sanitize_for_matrix('<code class="language-python">x = 1</code>')
        assert 'class="language-python"' in result

    def test_code_class_arbitrary_stripped(self) -> None:
        """code[class=foo] is not permitted; class attribute is removed."""
        from squidbot.adapters.channels.matrix_markdown import sanitize_for_matrix

        result = sanitize_for_matrix('<code class="foo">x = 1</code>')
        assert 'class="foo"' not in result
        assert "x = 1" in result

    def test_img_mxc_src_passes(self) -> None:
        """img[src=mxc://...] is permitted."""
        from squidbot.adapters.channels.matrix_markdown import sanitize_for_matrix

        result = sanitize_for_matrix('<img src="mxc://example.com/abc" alt="img">')
        assert 'src="mxc://example.com/abc"' in result

    def test_img_https_src_stripped(self) -> None:
        """img[src=https://...] is not permitted; src is removed."""
        from squidbot.adapters.channels.matrix_markdown import sanitize_for_matrix

        result = sanitize_for_matrix('<img src="https://evil.com/img.png" alt="img">')
        assert 'src="https://' not in result

    def test_a_href_javascript_stripped(self) -> None:
        """a[href=javascript:...] is stripped."""
        from squidbot.adapters.channels.matrix_markdown import sanitize_for_matrix

        result = sanitize_for_matrix('<a href="javascript:evil()">click</a>')
        assert "javascript" not in result

    def test_onclick_attribute_stripped(self) -> None:
        """onclick and other event attributes are removed."""
        from squidbot.adapters.channels.matrix_markdown import sanitize_for_matrix

        result = sanitize_for_matrix('<p onclick="evil()">text</p>')
        assert "onclick" not in result
        assert "text" in result
