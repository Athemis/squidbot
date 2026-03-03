"""Matrix-specific mistune plugins and HTML sanitizer for squidbot.

Provides:
- plugin_mx_math: mistune plugin that converts $$...$$ and $...$ LaTeX syntax
  to the Matrix spec v1.11+ data-mx-maths format.
- plugin_mx_spoiler: mistune plugin that converts ||text|| to Matrix
  data-mx-spoiler format.
- plugin_mx_block_spoiler: mistune plugin that converts >!-prefixed lines to
  Matrix data-mx-spoiler format as a block-level element.
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

__all__ = ["plugin_mx_math", "plugin_mx_spoiler", "plugin_mx_block_spoiler", "sanitize_for_matrix"]

# ---------------------------------------------------------------------------
# Math plugin
# ---------------------------------------------------------------------------

# Block math: multi-line form  $$\ncontent\n$$  or single-line form  $$content$$
# The single-line alternative uses a separate named group (math_text_s) because
# Python regex does not allow the same group name in two alternatives.
_BLOCK_MATH_PATTERN = (
    r"^ {0,3}\$\$[ \t]*\n(?P<math_text>[\s\S]+?)\n\$\$[ \t]*$"
    r"|^ {0,3}\$\$[ \t]*(?P<math_text_s>[^\n$][^\n]*?)[ \t]*\$\$[ \t]*$"
)
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

    def _parse_block_math(block: BlockParser, m: Any, state: BlockState) -> int:
        math_text: str = m.group("math_text") or m.group("math_text_s") or ""
        state.append_token({"type": "mx_block_math", "raw": math_text})
        return int(m.end()) + 1

    def _parse_inline_math(inline: InlineParser, m: Any, state: InlineState) -> int:
        state.append_token({"type": "mx_inline_math", "raw": m.group("math_text")})
        return int(m.end())

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
# Spoiler plugin
# ---------------------------------------------------------------------------

_INLINE_SPOILER_PATTERN = r"\|\|(?P<spoiler_text>.+?)\|\|"
_BLOCK_SPOILER_PATTERN = r"(?:^>![ \t]?[^\n]*(?:\n|$))+"


def plugin_mx_spoiler(md: Markdown) -> None:
    """Mistune plugin that renders ||text|| to Matrix data-mx-spoiler format.

    Inline spoiler syntax ||text|| becomes <span data-mx-spoiler>text</span>.
    The inner text is rendered recursively so nested inline Markdown works,
    e.g. ||**bold**|| produces <span data-mx-spoiler><strong>bold</strong></span>.

    Per Matrix Spec v1.17: data-mx-spoiler is only valid on <span> (inline).
    Block-level spoilers are out of scope.

    Args:
        md: The Markdown instance to extend.
    """

    def _parse_inline_spoiler(inline: InlineParser, m: Any, state: InlineState) -> int:
        text = m.group("spoiler_text")
        new_state = state.copy()
        new_state.src = text
        children = inline.render(new_state)
        state.append_token({"type": "mx_inline_spoiler", "children": children})
        return int(m.end())

    def _render_inline_spoiler(renderer: BaseRenderer, text: str) -> str:
        return f"<span data-mx-spoiler>{text}</span>"

    md.inline.register(
        "mx_inline_spoiler", _INLINE_SPOILER_PATTERN, _parse_inline_spoiler, before="link"
    )
    if md.renderer and md.renderer.NAME == "html":
        md.renderer.register("mx_inline_spoiler", _render_inline_spoiler)


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
        # Strip the '>!' prefix (and optional single space/tab) from each line.
        lines = []
        for line in raw.splitlines():
            if line.startswith(">! ") or line.startswith(">!\t"):
                lines.append(line[3:])
            elif line.rstrip() == ">!":
                lines.append("")
            elif line.startswith(">!"):
                lines.append(line[2:])  # bare ">!" with no separator
            else:
                lines.append(line)
        content = "\n".join(lines)
        # Use "text" key (not "raw") so mistune's _iter_render passes the content
        # through the inline parser before calling the renderer. Tokens with "raw"
        # bypass inline parsing entirely.
        state.append_token({"type": "mx_block_spoiler", "text": content})
        return int(m.end())

    def _render_block_spoiler(renderer: BaseRenderer, text: str) -> str:
        return f"<span data-mx-spoiler>{text}</span>\n"

    md.block.register(
        "mx_block_spoiler", _BLOCK_SPOILER_PATTERN, _parse_block_spoiler, before="block_quote"
    )
    if md.renderer and md.renderer.NAME == "html":
        md.renderer.register("mx_block_spoiler", _render_block_spoiler)


# ---------------------------------------------------------------------------
# nh3 sanitizer — Matrix spec v1.17 allowlist
# ---------------------------------------------------------------------------

_MATRIX_TAGS: set[str] = {
    "del",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "p",
    "a",
    "ul",
    "ol",
    "sup",
    "sub",
    "li",
    "b",
    "i",
    "u",
    "strong",
    "em",
    "s",
    "code",
    "hr",
    "br",
    "div",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "caption",
    "pre",
    "span",
    "img",
    "details",
    "summary",
}

# Attributes permitted per tag (Matrix spec v1.17).
# Tags not listed here permit no attributes.
_MATRIX_ATTRIBUTES: dict[str, set[str]] = {
    "span": {"data-mx-bg-color", "data-mx-color", "data-mx-spoiler", "data-mx-maths"},
    "a": {"href", "target"},
    "img": {"width", "height", "alt", "title", "src"},
    "ol": {"start"},
    "code": {"class"},
    "div": {"data-mx-maths"},
}

# "mxc" is included so nh3 does not reject mxc:// URIs before attribute_filter
# runs. attribute_filter then further constrains img[src] to mxc:// only.
_MATRIX_URL_SCHEMES: set[str] = {"https", "http", "ftp", "mailto", "magnet", "mxc"}

# Tags whose *content* must also be removed (not just the tag itself).
_MATRIX_CLEAN_CONTENT_TAGS: set[str] = {"script", "style"}


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
        return value if value.lower().startswith("mxc://") else None
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
