"""Safe URL fetch tool with bounded output for agent use.

The tool performs HTTP GET requests with SSRF protections, redirect checks, and
response-size limits. It returns readable text for HTML pages or raw text for
other textual content types.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlparse

import httpx

from squidbot.core.models import ToolResult
from squidbot.core.text_extract import html_to_text

_DEFAULT_TIMEOUT_SECONDS = 20
_DEFAULT_MAX_BYTES = 524_288
_DEFAULT_MAX_CHARS = 8_000
_MAX_REDIRECTS = 5
_LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain"}

type _IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
type _Resolver = Callable[[str], Awaitable[set[_IpAddress]]]


class FetchUrlTool:
    """Fetch an HTTP(S) URL safely and return bounded text."""

    name = "fetch_url"
    description = "Fetch a URL with SSRF/size safeguards and return readable text."
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "HTTP or HTTPS URL to fetch.",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Request timeout in seconds (default: 20).",
                "default": _DEFAULT_TIMEOUT_SECONDS,
            },
            "max_bytes": {
                "type": "integer",
                "description": "Maximum bytes to read from response body (default: 524288).",
                "default": _DEFAULT_MAX_BYTES,
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum output characters returned (default: 8000).",
                "default": _DEFAULT_MAX_CHARS,
            },
            "format": {
                "type": "string",
                "enum": ["text", "html"],
                "description": "Output format for HTML content.",
                "default": "text",
            },
        },
        "required": ["url"],
    }

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        resolver: _Resolver | None = None,
    ) -> None:
        self._client = client
        self._resolver: _Resolver = resolver or _resolve_host_ips

    async def execute(self, **kwargs: object) -> ToolResult:
        """Fetch a URL and return bounded text output.

        Args:
            **kwargs: Tool arguments (`url`, optional limits and `format`).

        Returns:
            ToolResult containing text content or an error description.
        """
        url_raw = kwargs.get("url")
        if not isinstance(url_raw, str) or not url_raw:
            return ToolResult(tool_call_id="", content="Error: url is required", is_error=True)
        url = url_raw.strip()

        timeout_raw = kwargs.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
        if isinstance(timeout_raw, int):
            timeout_seconds = timeout_raw
        elif isinstance(timeout_raw, str):
            try:
                timeout_seconds = int(timeout_raw)
            except ValueError:
                timeout_seconds = _DEFAULT_TIMEOUT_SECONDS
        else:
            timeout_seconds = _DEFAULT_TIMEOUT_SECONDS
        timeout_seconds = max(timeout_seconds, 1)

        max_bytes_raw = kwargs.get("max_bytes", _DEFAULT_MAX_BYTES)
        if isinstance(max_bytes_raw, int):
            max_bytes = max_bytes_raw
        elif isinstance(max_bytes_raw, str):
            try:
                max_bytes = int(max_bytes_raw)
            except ValueError:
                max_bytes = _DEFAULT_MAX_BYTES
        else:
            max_bytes = _DEFAULT_MAX_BYTES
        max_bytes = max(max_bytes, 1)

        max_chars_raw = kwargs.get("max_chars", _DEFAULT_MAX_CHARS)
        if isinstance(max_chars_raw, int):
            max_chars = max_chars_raw
        elif isinstance(max_chars_raw, str):
            try:
                max_chars = int(max_chars_raw)
            except ValueError:
                max_chars = _DEFAULT_MAX_CHARS
        else:
            max_chars = _DEFAULT_MAX_CHARS
        max_chars = max(max_chars, 1)

        format_raw = kwargs.get("format", "text")
        output_format = format_raw if isinstance(format_raw, str) else "text"
        if output_format not in {"text", "html"}:
            return ToolResult(
                tool_call_id="",
                content="Error: format must be 'text' or 'html'",
                is_error=True,
            )

        try:
            response, body = await self._fetch_with_redirects(
                url=url,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
            )
        except ValueError as exc:
            return ToolResult(tool_call_id="", content=f"Error: {exc}", is_error=True)
        except httpx.HTTPError as exc:
            return ToolResult(
                tool_call_id="", content=f"Error: request failed ({exc})", is_error=True
            )

        content_type = response.headers.get("content-type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        is_html = media_type in {"text/html", "application/xhtml+xml"}
        is_textual = media_type.startswith("text/") or media_type == "application/xhtml+xml"

        if not is_textual:
            return ToolResult(
                tool_call_id="",
                content=f"Error: unsupported content-type '{media_type or 'unknown'}'",
                is_error=True,
            )

        decoded = body.decode(response.encoding or "utf-8", errors="replace")
        if output_format == "html":
            return ToolResult(tool_call_id="", content=decoded[:max_chars])
        if is_html:
            return ToolResult(tool_call_id="", content=html_to_text(decoded)[:max_chars])
        return ToolResult(tool_call_id="", content=decoded[:max_chars])

    async def _fetch_with_redirects(
        self,
        *,
        url: str,
        timeout_seconds: int,
        max_bytes: int,
    ) -> tuple[httpx.Response, bytes]:
        parsed = _parse_and_validate_url(url)
        current_url = str(parsed)

        client = self._client
        if client is not None:
            return await self._fetch_with_client(
                client=client,
                url=current_url,
                max_bytes=max_bytes,
                timeout_seconds=timeout_seconds,
            )

        async with httpx.AsyncClient(
            timeout=timeout_seconds, follow_redirects=False
        ) as transient_client:
            return await self._fetch_with_client(
                client=transient_client,
                url=current_url,
                max_bytes=max_bytes,
                timeout_seconds=timeout_seconds,
            )

    async def _fetch_with_client(
        self,
        *,
        client: httpx.AsyncClient,
        url: str,
        max_bytes: int,
        timeout_seconds: int,
    ) -> tuple[httpx.Response, bytes]:
        current_url = url
        for _ in range(_MAX_REDIRECTS + 1):
            parsed = _parse_and_validate_url(current_url)
            await self._assert_safe_host(parsed.host)

            async with client.stream("GET", str(parsed), timeout=timeout_seconds) as response:
                if _is_redirect(response.status_code):
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("redirect response without Location header")
                    current_url = urljoin(str(response.request.url), location)
                    continue

                response.raise_for_status()
                body = await _read_body_limited(response, max_bytes=max_bytes)
                return response, body

        raise ValueError(f"too many redirects (>{_MAX_REDIRECTS})")

    async def _assert_safe_host(self, hostname: str | None) -> None:
        if not hostname:
            raise ValueError("URL host is required")

        hostname_lower = hostname.lower().rstrip(".")
        if hostname_lower in _LOCAL_HOSTNAMES or hostname_lower.endswith(".localhost"):
            raise ValueError("target host is blocked by SSRF policy")

        try:
            literal_ip = ipaddress.ip_address(hostname_lower)
        except ValueError:
            addresses = await self._resolver(hostname_lower)
            if not addresses:
                raise ValueError("could not resolve hostname") from None
            for address in addresses:
                _assert_public_ip(address)
            return

        _assert_public_ip(literal_ip)


def _parse_and_validate_url(url: str) -> httpx.URL:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("only http and https URLs are allowed")
    if not parsed.netloc:
        raise ValueError("URL host is required")
    return httpx.URL(url)


def _is_redirect(status_code: int) -> bool:
    return status_code in {301, 302, 303, 307, 308}


def _assert_public_ip(address: _IpAddress) -> None:
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
    ):
        raise ValueError("target host is blocked by SSRF policy")


async def _resolve_host_ips(hostname: str) -> set[_IpAddress]:
    infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None, type=socket.SOCK_STREAM)
    addresses: set[_IpAddress] = set()
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        host = sockaddr[0]
        addresses.add(ipaddress.ip_address(host))
    return addresses


async def _read_body_limited(response: httpx.Response, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        if not chunk:
            continue
        remaining = max_bytes - total
        if remaining <= 0:
            break
        if len(chunk) > remaining:
            chunks.append(chunk[:remaining])
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)
