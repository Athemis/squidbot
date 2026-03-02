"""Shared Markdown configuration for channel adapters.

Defines the common set of mistune plugins enabled for Markdown-to-HTML rendering
in Matrix and Email channels.
"""

from __future__ import annotations

MARKDOWN_PLUGINS: tuple[str, ...] = (
    "table",
    "strikethrough",
    "task_lists",
    "url",
    "footnotes",
    "superscript",
    "subscript",
)
