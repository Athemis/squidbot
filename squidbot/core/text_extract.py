"""Utilities for extracting readable text from HTML.

This module provides lightweight, dependency-free text extraction helpers used by
multiple adapters. It intentionally keeps behavior simple and bounded for safety
and predictability in channels and tools.
"""

from __future__ import annotations

import html
import html.parser

_SKIP_TAGS: frozenset[str] = frozenset({"script", "style", "head"})


class _HtmlTextStripper(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip: int = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _SKIP_TAGS and self._skip > 0:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def html_to_text(html_body: str) -> str:
    """Strip HTML tags and decode entities to produce plain text.

    Args:
        html_body: HTML document or fragment.

    Returns:
        Plain-text extraction with script/style/head content removed.
    """
    stripper = _HtmlTextStripper()
    stripper.feed(html_body)
    return html.unescape(stripper.get_text())
