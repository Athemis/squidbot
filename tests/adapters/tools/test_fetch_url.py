"""Tests for FetchUrlTool."""

from __future__ import annotations

import ipaddress

import httpx

from squidbot.adapters.tools.fetch_url import FetchUrlTool


async def _resolve_public(_: str) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    return {ipaddress.ip_address("93.184.216.34")}


class TestFetchUrlTool:
    async def test_html_to_text_output(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "https://example.com/page"
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text=(
                    "<html><head><title>Hidden</title></head>"
                    "<body><p>Hello <b>web</b></p></body></html>"
                ),
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            tool = FetchUrlTool(client=client, resolver=_resolve_public)
            result = await tool.execute(url="https://example.com/page")

        assert not result.is_error
        assert "Hello" in result.content
        assert "web" in result.content
        assert "Hidden" not in result.content
        assert "<p>" not in result.content

    async def test_redirect_allowed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == "https://example.com/start":
                return httpx.Response(
                    302,
                    headers={"location": "https://example.com/final"},
                    request=request,
                )
            if str(request.url) == "https://example.com/final":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/plain; charset=utf-8"},
                    text="redirect ok",
                    request=request,
                )
            return httpx.Response(404, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            tool = FetchUrlTool(client=client, resolver=_resolve_public)
            result = await tool.execute(url="https://example.com/start")

        assert not result.is_error
        assert result.content == "redirect ok"

    async def test_redirect_to_private_ip_blocked(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302,
                headers={"location": "http://127.0.0.1/internal"},
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            tool = FetchUrlTool(client=client, resolver=_resolve_public)
            result = await tool.execute(url="https://example.com/start")

        assert result.is_error
        assert "blocked by SSRF policy" in result.content

    async def test_max_bytes_truncates_streamed_body(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text="<p>abcdefghijklmnopqrstuvwxyz</p>",
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            tool = FetchUrlTool(client=client, resolver=_resolve_public)
            result = await tool.execute(
                url="https://example.com/page",
                format="html",
                max_bytes=10,
                max_chars=100,
            )

        assert not result.is_error
        assert result.content == "<p>abcdefg"
