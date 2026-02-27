"""Tests for shared HTML text extraction helpers."""

from __future__ import annotations

from squidbot.core.text_extract import html_to_text


class TestHtmlToText:
    def test_removes_html_tags(self) -> None:
        result = html_to_text("<p>Hello <b>world</b></p>")
        assert "Hello" in result
        assert "world" in result
        assert "<p>" not in result
        assert "<b>" not in result

    def test_skips_script_style_and_head_content(self) -> None:
        html = (
            "<head><title>Hidden title</title></head>"
            "<style>body { color: red; }</style>"
            "<script>alert('x')</script>"
            "<p>Visible text</p>"
        )
        result = html_to_text(html)
        assert "Visible text" in result
        assert "Hidden title" not in result
        assert "alert" not in result
        assert "color" not in result

    def test_unescapes_html_entities(self) -> None:
        result = html_to_text("Fish &amp; Chips &lt;3")
        assert result == "Fish & Chips <3"
