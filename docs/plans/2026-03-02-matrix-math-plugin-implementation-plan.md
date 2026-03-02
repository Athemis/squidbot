# Matrix Math Plugin & HTML Passthrough — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Matrix-Nachrichten rendern LaTeX-Formeln via `data-mx-maths` und erlauben Raw-HTML-Passthrough (z.B. `<details>`, `<u>`, `<span data-mx-spoiler>`) — abgesichert durch einen nh3-Sanitizer mit Matrix-Spec-v1.17-Allowlist.

**Architecture:** Neues Modul `squidbot/adapters/channels/matrix_markdown.py` mit `plugin_mx_math` (Latex-Syntax → `data-mx-maths`) und `sanitize_for_matrix()` (nh3-Cleaner). `matrix.py` schaltet auf `escape=False` um und wendet den Sanitizer post-render an. Email-Adapter bleibt unverändert.

**Tech Stack:** mistune>=3.0 (vorhanden), nh3>=0.2 (neu), html (stdlib)

---

### Task 1: nh3 als Abhängigkeit hinzufügen

**Files:**
- Modify: `pyproject.toml`

**Step 1: Zeile in dependencies einfügen**

In `pyproject.toml` nach `"mistune>=3.0",` einfügen:

```toml
    "nh3>=0.2",
```

**Step 2: Sync und Installation prüfen**

```bash
CMAKE_POLICY_VERSION_MINIMUM=3.5 uv sync
uv run python3 -c "import nh3; print(nh3.__version__)"
```

Erwartet: Versionsnummer ohne Fehler.

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add nh3 HTML sanitizer"
```

---

### Task 2: Failing Tests schreiben

**Files:**
- Modify: `tests/adapters/channels/test_markdown_plugins.py` (zwei neue Klassen am Ende)

**Step 1: Test-Klassen schreiben**

Ans Ende von `test_markdown_plugins.py` anhängen:

```python
class TestMatrixMathPlugin:
    """Test Matrix-specific math plugin renders to data-mx-maths attributes.

    Tests verify that block ($$...$$) and inline ($...$) math syntax is
    converted to the Matrix spec v1.11+ format: data-mx-maths attribute
    with a <code> fallback for non-LaTeX clients.
    """

    def test_block_math_renders_div_with_data_mx_maths(self) -> None:
        """Block math $$...$$ renders to <div data-mx-maths="...">."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("$$\nE=mc^2\n$$")
        assert '<div data-mx-maths="E=mc^2">' in result
        assert "<code>E=mc^2</code>" in result

    def test_inline_math_renders_span_with_data_mx_maths(self) -> None:
        """Inline math $...$ renders to <span data-mx-maths="...">."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("The formula $E=mc^2$ is famous.")
        assert '<span data-mx-maths="E=mc^2">' in result
        assert "<code>E=mc^2</code>" in result

    def test_block_math_quotes_escaped_in_attribute(self) -> None:
        """LaTeX containing double quotes is safely escaped in data-mx-maths attribute."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown('$$\n\\text{"hello"}\n$$')
        # The attribute value must not contain unescaped quotes
        attr_part = result.split('data-mx-maths="')[1].split('"')[0]
        assert '"' not in attr_part

    def test_block_math_multiline(self) -> None:
        """Multi-line block math content is preserved."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("$$\na^2 + b^2 = c^2\n$$")
        assert "data-mx-maths=" in result
        assert "a^2" in result

    def test_math_does_not_appear_in_email(self) -> None:
        """Email _md does NOT render data-mx-maths (Matrix-only plugin)."""
        from squidbot.adapters.channels.email import _md

        result = _md("$$\nE=mc^2\n$$")
        assert "data-mx-maths" not in result

    def test_math_coexists_with_other_plugins(self) -> None:
        """Math plugin works alongside strikethrough and table plugins."""
        from squidbot.adapters.channels.matrix import _render_markdown

        result = _render_markdown("~~old~~ value: $x^2$\n\n$$\n\\alpha\n$$")
        assert "<del>old</del>" in result
        assert "data-mx-maths" in result


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

        result = sanitize_for_matrix('<span data-mx-spoiler="spoiler">hidden</span>')
        assert "data-mx-spoiler" in result
        assert "hidden" in result

    def test_span_data_mx_maths_passes(self) -> None:
        """<span data-mx-maths> produced by plugin passes nh3 unchanged."""
        from squidbot.adapters.channels.matrix_markdown import sanitize_for_matrix

        result = sanitize_for_matrix('<span data-mx-maths="x^2"><code>x^2</code></span>')
        assert 'data-mx-maths="x^2"' in result

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
```

**Step 2: Sicherstellen dass Tests fehlschlagen**

```bash
uv run pytest tests/adapters/channels/test_markdown_plugins.py::TestMatrixMathPlugin tests/adapters/channels/test_markdown_plugins.py::TestSanitizeForMatrix -v
```

Erwartet: FAIL — `ImportError` oder `AssertionError`.

**Step 3: Commit**

```bash
git add tests/adapters/channels/test_markdown_plugins.py
git commit -m "test: add failing tests for Matrix math plugin and nh3 sanitizer"
```

---

### Task 3: `squidbot/adapters/channels/matrix_markdown.py` implementieren

**Files:**
- Create: `squidbot/adapters/channels/matrix_markdown.py`

**Step 1: Datei schreiben**

```python
"""Matrix-specific mistune plugin and HTML sanitizer for squidbot.

Provides:
- plugin_mx_math: mistune plugin that converts $...$ and $$...$$ LaTeX syntax
  to the Matrix spec v1.11+ data-mx-maths format.
- sanitize_for_matrix: nh3-based HTML sanitizer enforcing the Matrix spec
  v1.17 permitted HTML allowlist.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING, Any

import nh3

if TYPE_CHECKING:
    from mistune import Markdown
    from mistune.block_parser import BlockParser
    from mistune.core import BaseRenderer, BlockState, InlineState
    from mistune.inline_parser import InlineParser

__all__ = ["plugin_mx_math", "sanitize_for_matrix"]

# ---------------------------------------------------------------------------
# Math plugin
# ---------------------------------------------------------------------------

# Reuse the same patterns as mistune's built-in math plugin.
_BLOCK_MATH_PATTERN = r"^ {0,3}\$\$[ \t]*\n(?P<math_text>[\s\S]+?)\n\$\$[ \t]*$"
_INLINE_MATH_PATTERN = r"\$(?!\s)(?P<math_text>.+?)(?!\s)\$"


def plugin_mx_math(md: Markdown) -> None:
    """Mistune plugin that renders math to Matrix data-mx-maths format.

    Block math ($$...$$) becomes <div data-mx-maths="...">.
    Inline math ($...$) becomes <span data-mx-maths="...">.
    The LaTeX source is HTML-escaped in the attribute; <code> provides a
    plain-text fallback for clients that cannot render LaTeX.

    Per Matrix Spec v1.11 (MSC2191): clients that support math read the
    data-mx-maths attribute; clients without LaTeX support show the child.

    Args:
        md: The Markdown instance to extend.
    """

    def _parse_block_math(
        block: BlockParser, m: Any, state: BlockState
    ) -> int:
        state.append_token({"type": "mx_block_math", "raw": m.group("math_text")})
        return m.end() + 1

    def _parse_inline_math(
        inline: InlineParser, m: Any, state: InlineState
    ) -> int:
        state.append_token({"type": "mx_inline_math", "raw": m.group("math_text")})
        return m.end()

    def _render_block_math(renderer: BaseRenderer, text: str) -> str:
        attr = html.escape(text, quote=True)
        body = html.escape(text, quote=False)
        return f'<div data-mx-maths="{attr}"><code>{body}</code></div>\n'

    def _render_inline_math(renderer: BaseRenderer, text: str) -> str:
        attr = html.escape(text, quote=True)
        body = html.escape(text, quote=False)
        return f'<span data-mx-maths="{attr}"><code>{body}</code></span>'

    md.block.register("mx_block_math", _BLOCK_MATH_PATTERN, _parse_block_math, before="list")
    md.inline.register("mx_inline_math", _INLINE_MATH_PATTERN, _parse_inline_math, before="link")
    if md.renderer and md.renderer.NAME == "html":
        md.renderer.register("mx_block_math", _render_block_math)
        md.renderer.register("mx_inline_math", _render_inline_math)


# ---------------------------------------------------------------------------
# nh3 sanitizer — Matrix spec v1.17 allowlist
# ---------------------------------------------------------------------------

_MATRIX_TAGS: frozenset[str] = frozenset({
    "del", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "p", "a", "ul", "ol", "sup", "sub", "li",
    "b", "i", "u", "strong", "em", "s", "code", "hr", "br",
    "div", "table", "thead", "tbody", "tr", "th", "td", "caption",
    "pre", "span", "img", "details", "summary",
})

# Attributes permitted per tag (Matrix spec v1.17).
# Tags not listed here permit no attributes.
_MATRIX_ATTRIBUTES: dict[str, set[str]] = {
    "span": {"data-mx-bg-color", "data-mx-color", "data-mx-spoiler", "data-mx-maths"},
    "a":    {"href", "target"},
    "img":  {"width", "height", "alt", "title", "src"},
    "ol":   {"start"},
    "code": {"class"},
    "div":  {"data-mx-maths"},
}

# "mxc" is included so nh3 does not reject mxc:// URIs before attribute_filter
# can run. attribute_filter then further constrains img[src] to mxc:// only.
_MATRIX_URL_SCHEMES: frozenset[str] = frozenset({
    "https", "http", "ftp", "mailto", "magnet", "mxc",
})

# Tags whose *content* must also be removed (not just the tag itself).
_MATRIX_CLEAN_CONTENT_TAGS: frozenset[str] = frozenset({"script", "style"})


def _matrix_attr_filter(tag: str, attr: str, value: str) -> str | None:
    """Attribute-level filter for Matrix spec constraints.

    Enforces two rules that cannot be expressed via the attributes dict alone:
    - code[class] must start with "language-"
    - img[src] must be a mxc:// URI

    Args:
        tag: HTML element name.
        attr: Attribute name.
        value: Attribute value.

    Returns:
        The (possibly unchanged) value to keep, or None to remove the attribute.
    """
    if tag == "code" and attr == "class":
        return value if value.startswith("language-") else None
    if tag == "img" and attr == "src":
        return value if value.startswith("mxc://") else None
    return value


_MATRIX_SANITIZER: nh3.Cleaner = nh3.Cleaner(
    tags=_MATRIX_TAGS,
    attributes=_MATRIX_ATTRIBUTES,
    url_schemes=_MATRIX_URL_SCHEMES,
    clean_content_tags=_MATRIX_CLEAN_CONTENT_TAGS,
    attribute_filter=_matrix_attr_filter,
    # Default link_rel="noopener noreferrer" is kept — correct for outgoing links.
)


def sanitize_for_matrix(rendered_html: str) -> str:
    """Sanitize rendered HTML against the Matrix spec v1.17 permitted HTML allowlist.

    Strips any tag or attribute not explicitly permitted by the Matrix spec.
    Content inside unknown tags is preserved; content inside <script>/<style>
    is removed entirely.

    Args:
        rendered_html: Raw HTML string produced by the mistune renderer.

    Returns:
        Sanitized HTML safe to use as formatted_body in a Matrix message.
    """
    return _MATRIX_SANITIZER.clean(rendered_html)
```

**Step 2: Ruff und mypy prüfen**

```bash
uv run ruff check squidbot/adapters/channels/matrix_markdown.py
uv run mypy squidbot/adapters/channels/matrix_markdown.py
```

Erwartet: keine Fehler.

**Step 3: Sanitizer-Tests laufen lassen**

```bash
uv run pytest tests/adapters/channels/test_markdown_plugins.py::TestSanitizeForMatrix -v
```

Erwartet: alle Sanitizer-Tests PASS.

**Step 4: Commit**

```bash
git add squidbot/adapters/channels/matrix_markdown.py
git commit -m "feat(matrix): add plugin_mx_math and Matrix spec v1.17 nh3 sanitizer"
```

---

### Task 4: `matrix.py` aktualisieren

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`

**Step 1: Imports ergänzen**

Nach der Zeile `from squidbot.core.markdown import MARKDOWN_PLUGINS` einfügen:

```python
from squidbot.adapters.channels.matrix_markdown import plugin_mx_math, sanitize_for_matrix
```

**Step 2: Mistune-Instanz und `_render_markdown` anpassen**

Zeile 66 ändern von:
```python
_md = mistune.create_markdown(escape=True, plugins=list(MARKDOWN_PLUGINS))
```
zu:
```python
_md = mistune.create_markdown(escape=False, plugins=[*MARKDOWN_PLUGINS, plugin_mx_math])
```

Funktion `_render_markdown` (Zeile 88–91) ändern von:
```python
def _render_markdown(text: str) -> str:
    """Render Markdown to HTML for Matrix formatted_body."""
    rendered = cast(str, _md(text))
    return rendered.strip()
```
zu:
```python
def _render_markdown(text: str) -> str:
    """Render Markdown to HTML for Matrix formatted_body.

    Passes raw HTML through mistune (escape=False), applies plugin_mx_math
    for LaTeX → data-mx-maths conversion, then sanitizes the result with
    the Matrix spec v1.17 nh3 allowlist.
    """
    rendered = cast(str, _md(text)).strip()
    return sanitize_for_matrix(rendered)
```

**Step 3: Alle Math- und Sanitizer-Tests laufen lassen**

```bash
uv run pytest tests/adapters/channels/test_markdown_plugins.py::TestMatrixMathPlugin tests/adapters/channels/test_markdown_plugins.py::TestSanitizeForMatrix -v
```

Erwartet: alle Tests PASS.

**Step 4: Commit**

```bash
git add squidbot/adapters/channels/matrix.py
git commit -m "feat(matrix): enable HTML passthrough with nh3 sanitizer and math plugin"
```

---

### Task 5: Vollständige Verifikation

**Step 1: Alle Plugin-Tests (inkl. Regressionstests)**

```bash
uv run pytest tests/adapters/channels/test_markdown_plugins.py -v
```

Erwartet: alle Tests PASS.

**Step 2: Linting, Formatierung, Typen**

```bash
uv run ruff check . && uv run ruff format . --check && uv run mypy squidbot/
```

Erwartet: keine Fehler.

**Step 3: Gesamte Test-Suite**

```bash
uv run pytest
```

Erwartet: alle Tests PASS.

**Step 4: Commit falls nötig**

```bash
git add -p
git commit -m "chore: verify matrix math plugin and sanitizer integration"
```

---

## Summary

| Task | Beschreibung                         | Geänderte Dateien                                           |
| ---- | ------------------------------------ | ----------------------------------------------------------- |
| 1    | nh3 Dependency                       | `pyproject.toml`, `uv.lock`                                 |
| 2    | Failing Tests                        | `tests/adapters/channels/test_markdown_plugins.py`          |
| 3    | Plugin + Sanitizer implementieren    | `squidbot/adapters/channels/matrix_markdown.py` (neu)       |
| 4    | matrix.py verdrahten                 | `squidbot/adapters/channels/matrix.py`                      |
| 5    | Verifikation                         | —                                                           |
