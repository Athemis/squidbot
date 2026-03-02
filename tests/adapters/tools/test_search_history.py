"""
Tests for the search_history tool.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from squidbot.adapters.persistence.jsonl import JsonlMemory, _history_file
from squidbot.adapters.tools.search_history import SearchHistoryTool
from squidbot.core.models import Message


@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def memory(sessions_dir: Path) -> JsonlMemory:
    return JsonlMemory(base_dir=sessions_dir)


@pytest.fixture
def tool(sessions_dir: Path) -> SearchHistoryTool:
    return SearchHistoryTool(base_dir=sessions_dir)


async def test_finds_match_in_single_session(memory: JsonlMemory, tool: SearchHistoryTool) -> None:
    await memory.append_message(Message(role="user", content="What about Python packaging?"))
    await memory.append_message(
        Message(role="assistant", content="We discussed uv as package manager.")
    )

    result = await tool.execute(query="Python packaging")
    assert result.is_error is False
    assert "Python packaging" in result.content
    assert "uv" in result.content


async def test_case_insensitive_search(memory: JsonlMemory, tool: SearchHistoryTool) -> None:
    await memory.append_message(Message(role="user", content="DOCKER configuration"))

    result = await tool.execute(query="docker")
    assert result.is_error is False
    assert "DOCKER" in result.content


async def test_searches_across_multiple_sessions(
    memory: JsonlMemory, tool: SearchHistoryTool
) -> None:
    await memory.append_message(Message(role="user", content="Project Alpha started."))
    await memory.append_message(Message(role="user", content="Project Beta discussion."))

    result = await tool.execute(query="Project")
    assert result.is_error is False
    assert "Alpha" in result.content
    assert "Beta" in result.content


async def test_days_filter_excludes_old_messages(
    memory: JsonlMemory, tool: SearchHistoryTool
) -> None:
    old_msg = dataclasses.replace(
        Message(role="user", content="Old topic about legacy code."),
        timestamp=datetime.now() - timedelta(days=10),
    )
    await memory.append_message(old_msg)
    await memory.append_message(Message(role="user", content="Recent topic about new features."))

    result = await tool.execute(query="topic", days=5)
    assert result.is_error is False
    assert "Recent topic" in result.content
    assert "Old topic" not in result.content


async def test_max_results_cap(memory: JsonlMemory, tool: SearchHistoryTool) -> None:
    for i in range(20):
        await memory.append_message(Message(role="user", content=f"Find me number {i}"))

    result = await tool.execute(query="Find me", max_results=5)
    assert result.is_error is False
    assert result.content.count("## Match") <= 5


async def test_no_matches_returns_friendly_message(tool: SearchHistoryTool) -> None:
    result = await tool.execute(query="nonexistent")
    assert result.is_error is False
    assert "No matches found" in result.content


async def test_tool_calls_excluded_from_search(
    memory: JsonlMemory, tool: SearchHistoryTool
) -> None:
    from squidbot.core.models import ToolCall

    await memory.append_message(Message(role="user", content="Search for secrets"))
    await memory.append_message(
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="tc1", name="read_file", arguments={"path": "/etc/secrets"})],
        ),
    )
    await memory.append_message(
        Message(role="tool", content="secret data here", tool_call_id="tc1")
    )

    result = await tool.execute(query="secrets")
    assert result.is_error is False
    assert "Search for secrets" in result.content
    assert "secret data here" not in result.content


async def test_context_includes_surrounding_messages(
    memory: JsonlMemory, tool: SearchHistoryTool
) -> None:
    await memory.append_message(Message(role="user", content="Before context."))
    await memory.append_message(Message(role="user", content="Target keyword here."))
    await memory.append_message(Message(role="assistant", content="After context response."))

    result = await tool.execute(query="Target keyword")
    assert result.is_error is False
    assert "Before context" in result.content
    assert "After context response" in result.content


async def test_query_required(tool: SearchHistoryTool) -> None:
    result = await tool.execute()
    assert result.is_error is True
    assert "query is required" in result.content.lower()


@pytest.mark.asyncio
async def test_search_finds_match_in_global_history(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.append_message(
        Message(
            role="user",
            content="the release is ready",
            channel="matrix",
            sender_id="@alex:matrix.org",
        )
    )
    await storage.append_message(
        Message(role="assistant", content="great!", channel="matrix", sender_id="assistant")
    )

    tool = SearchHistoryTool(base_dir=tmp_path)
    result = await tool.execute(query="release")
    assert not result.is_error
    assert "matrix" in result.content
    assert "@alex:matrix.org" in result.content


@pytest.mark.asyncio
async def test_search_returns_no_match_message(tmp_path: Path) -> None:
    tool = SearchHistoryTool(base_dir=tmp_path)
    result = await tool.execute(query="nonexistent")
    assert not result.is_error
    assert "No matches" in result.content


@pytest.mark.asyncio
async def test_search_respects_days_filter(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    old_msg = dataclasses.replace(
        Message(role="user", content="old topic", channel="cli", sender_id="alex"),
        timestamp=datetime.now() - timedelta(days=10),
    )
    await storage.append_message(old_msg)
    await storage.append_message(
        Message(role="user", content="old topic recent", channel="cli", sender_id="alex")
    )

    tool = SearchHistoryTool(base_dir=tmp_path)
    result = await tool.execute(query="old topic", days=5)
    assert not result.is_error
    # Only the recent message should match (within last 5 days)
    assert "old topic recent" in result.content
    # The old message (10 days ago) must NOT appear
    assert result.content.count("old topic") == result.content.count("old topic recent")


@pytest.mark.asyncio
async def test_search_skips_malformed_jsonl_lines(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.append_message(
        Message(role="user", content="Find malformed data safely", channel="cli", sender_id="alex")
    )

    history_path = _history_file(tmp_path)
    with history_path.open("a", encoding="utf-8") as history_file:
        history_file.write("{this-is-not-json}\n")

    await storage.append_message(
        Message(
            role="assistant", content="Still searchable response", channel="cli", sender_id="bot"
        )
    )

    tool = SearchHistoryTool(base_dir=tmp_path)
    result = await tool.execute(query="malformed data")
    assert not result.is_error
    assert "Find malformed data safely" in result.content
    assert "Still searchable response" in result.content


def test_deserialize_not_called_for_non_matching_lines(tmp_path: Path) -> None:
    """deserialize_message_safe must not be called for lines that cannot contain the query.

    Lines that don't contain the query string (checked via a fast substring scan of the
    raw JSONL text) must be skipped entirely — JSON parsing must not be invoked for them.
    Lines that are used as context (immediately adjacent to a match) are exempt from this
    rule because they need to be parsed to populate the context window.
    """
    from unittest.mock import patch
    from squidbot.adapters.persistence.jsonl import _serialize_message, deserialize_message_safe
    from squidbot.core.models import Message
    from datetime import datetime

    history_file = tmp_path / "history.jsonl"
    # Layout: two non-matching lines, then the match.
    # The line immediately before the match may be lazily parsed for before-context,
    # but the earlier non-matching lines must NOT be deserialized at all.
    early_noise_a = Message(role="user", content="alpha noise", channel="c", sender_id="u")
    early_noise_b = Message(role="user", content="beta noise", channel="c", sender_id="u")
    context_before = Message(
        role="user", content="context before the hit", channel="c", sender_id="u"
    )
    matching = Message(role="user", content="find me please", channel="c", sender_id="u")
    history_file.write_text(
        "\n".join(
            [
                _serialize_message(early_noise_a),
                _serialize_message(early_noise_b),
                _serialize_message(context_before),
                _serialize_message(matching),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    deserialized_contents: list[str] = []
    real_dsafe = deserialize_message_safe

    def tracking_dsafe(line: str) -> Message | None:
        parsed = real_dsafe(line)
        if parsed is not None and isinstance(parsed.content, str):
            deserialized_contents.append(parsed.content)
        return parsed

    with patch(
        "squidbot.adapters.tools.search_history.deserialize_message_safe",
        side_effect=tracking_dsafe,
    ):
        from squidbot.adapters.tools.search_history import _scan_history

        results = _scan_history(
            tmp_path,
            "find me please",
            cutoff=datetime(2000, 1, 1),
            max_results=10,
        )

    assert len(results) == 1
    # Lines that clearly cannot contain the query must not be deserialized.
    assert "alpha noise" not in deserialized_contents, (
        f"Non-adjacent non-matching line was deserialized: {deserialized_contents}"
    )
    assert "beta noise" not in deserialized_contents, (
        f"Non-adjacent non-matching line was deserialized: {deserialized_contents}"
    )
