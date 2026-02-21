"""Tests for WebSearchTool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from squidbot.adapters.tools.web_search import WebSearchTool
from squidbot.config.schema import WebSearchConfig


def _config(
    provider: str = "searxng", url: str = "http://searx.local", api_key: str = ""
) -> WebSearchConfig:
    return WebSearchConfig(enabled=True, provider=provider, url=url, api_key=api_key)


class TestWebSearchToolInterface:
    def test_name(self):
        tool = WebSearchTool(config=_config())
        assert tool.name == "web_search"

    def test_description_mentions_search(self):
        tool = WebSearchTool(config=_config())
        assert "search" in tool.description.lower()

    def test_parameters_has_query(self):
        tool = WebSearchTool(config=_config())
        assert "query" in tool.parameters["properties"]
        assert "query" in tool.parameters.get("required", [])

    def test_parameters_has_max_results(self):
        tool = WebSearchTool(config=_config())
        assert "max_results" in tool.parameters["properties"]

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            WebSearchTool(config=_config(provider="bing"))

    def test_brave_missing_api_key_raises(self):
        with pytest.raises(ValueError, match="api_key"):
            WebSearchTool(config=_config(provider="brave", api_key=""))


class TestWebSearchToolSearxng:
    @pytest.mark.asyncio
    async def test_returns_formatted_results(self):
        tool = WebSearchTool(config=_config(provider="searxng", url="http://searx.local"))
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "results": [
                {"title": "Page One", "url": "https://one.com", "content": "Snippet one."},
                {"title": "Page Two", "url": "https://two.com", "content": "Snippet two."},
            ]
        }
        with patch("squidbot.adapters.tools.web_search.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=fake_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tool.execute(query="test query", max_results=2)

        assert not result.is_error
        assert "Page One" in result.content
        assert "https://one.com" in result.content
        assert "Snippet one." in result.content

    @pytest.mark.asyncio
    async def test_empty_results(self):
        tool = WebSearchTool(config=_config(provider="searxng"))
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {"results": []}
        with patch("squidbot.adapters.tools.web_search.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=fake_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tool.execute(query="nothing", max_results=5)

        assert not result.is_error
        assert "No results" in result.content

    @pytest.mark.asyncio
    async def test_http_error_returns_error_result(self):
        tool = WebSearchTool(config=_config(provider="searxng"))
        with patch("squidbot.adapters.tools.web_search.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tool.execute(query="test", max_results=5)

        assert result.is_error
        assert "Search failed" in result.content

    @pytest.mark.asyncio
    async def test_http_status_error_returns_error_result(self):
        """HTTP 4xx/5xx from raise_for_status() should return an error result."""
        tool = WebSearchTool(config=_config(provider="searxng"))
        fake_response = MagicMock()
        fake_response.raise_for_status.side_effect = Exception("404 Not Found")
        with patch("squidbot.adapters.tools.web_search.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=fake_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tool.execute(query="test", max_results=5)

        assert result.is_error
        assert "Search failed" in result.content

    @pytest.mark.asyncio
    async def test_max_results_limits_output(self):
        """max_results should limit the number of results returned."""
        tool = WebSearchTool(config=_config(provider="searxng"))
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "results": [
                {"title": f"Result {i}", "url": f"https://r{i}.com", "content": f"Snippet {i}."}
                for i in range(5)
            ]
        }
        with patch("squidbot.adapters.tools.web_search.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=fake_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tool.execute(query="test", max_results=2)

        assert not result.is_error
        assert "Result 0" in result.content
        assert "Result 1" in result.content
        assert "Result 2" not in result.content


class TestWebSearchToolDdg:
    @pytest.mark.asyncio
    async def test_returns_formatted_results(self):
        tool = WebSearchTool(config=_config(provider="duckduckgo"))
        fake_results = [
            {"title": "DDG One", "href": "https://ddg-one.com", "body": "DDG snippet."},
        ]
        with patch(
            "squidbot.adapters.tools.web_search.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=fake_results,
        ):
            result = await tool.execute(query="ddg test", max_results=1)

        assert not result.is_error
        assert "DDG One" in result.content
        assert "https://ddg-one.com" in result.content
        assert "DDG snippet." in result.content

    @pytest.mark.asyncio
    async def test_error_returns_error_result(self):
        tool = WebSearchTool(config=_config(provider="duckduckgo"))
        with patch(
            "squidbot.adapters.tools.web_search.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=Exception("ddg error"),
        ):
            result = await tool.execute(query="test", max_results=5)

        assert result.is_error
        assert "Search failed" in result.content


class TestWebSearchToolBrave:
    @pytest.mark.asyncio
    async def test_returns_formatted_results(self):
        tool = WebSearchTool(config=_config(provider="brave", api_key="test-key"))
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "web": {
                "results": [
                    {
                        "title": "Brave One",
                        "url": "https://brave-one.com",
                        "description": "Brave snippet.",
                    },
                ]
            }
        }
        with patch("squidbot.adapters.tools.web_search.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=fake_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tool.execute(query="brave test", max_results=1)

        assert not result.is_error
        assert "Brave One" in result.content
        assert "https://brave-one.com" in result.content

    @pytest.mark.asyncio
    async def test_http_error_returns_error_result(self):
        tool = WebSearchTool(config=_config(provider="brave", api_key="test-key"))
        with patch("squidbot.adapters.tools.web_search.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tool.execute(query="test", max_results=5)

        assert result.is_error
        assert "Search failed" in result.content
