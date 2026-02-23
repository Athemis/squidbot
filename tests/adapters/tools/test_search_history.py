"""
Tests for the search_history tool.
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from squidbot.adapters.persistence.jsonl import JsonlMemory
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


async def test_finds_match_in_single_session(memory: JsonlMemory, tool: SearchHistoryTool):
    await memory.append_message(
        "cli:local", Message(role="user", content="What about Python packaging?")
    )
    await memory.append_message(
        "cli:local", Message(role="assistant", content="We discussed uv as package manager.")
    )

    result = await tool.execute(query="Python packaging")
    assert result.is_error is False
    assert "Python packaging" in result.content
    assert "uv" in result.content


async def test_case_insensitive_search(memory: JsonlMemory, tool: SearchHistoryTool):
    await memory.append_message("cli:local", Message(role="user", content="DOCKER configuration"))

    result = await tool.execute(query="docker")
    assert result.is_error is False
    assert "DOCKER" in result.content


async def test_searches_across_multiple_sessions(memory: JsonlMemory, tool: SearchHistoryTool):
    await memory.append_message("cli:local", Message(role="user", content="Project Alpha started."))
    await memory.append_message(
        "matrix:user", Message(role="user", content="Project Beta discussion.")
    )

    result = await tool.execute(query="Project")
    assert result.is_error is False
    assert "Alpha" in result.content
    assert "Beta" in result.content


async def test_days_filter_excludes_old_messages(memory: JsonlMemory, tool: SearchHistoryTool):
    old_msg = Message(role="user", content="Old topic about legacy code.")
    old_msg.timestamp = datetime.now() - timedelta(days=10)
    await memory.append_message("cli:local", old_msg)

    await memory.append_message(
        "cli:local", Message(role="user", content="Recent topic about new features.")
    )

    result = await tool.execute(query="topic", days=5)
    assert result.is_error is False
    assert "Recent topic" in result.content
    assert "Old topic" not in result.content


async def test_max_results_cap(memory: JsonlMemory, tool: SearchHistoryTool):
    for i in range(20):
        await memory.append_message(
            "cli:local", Message(role="user", content=f"Find me number {i}")
        )

    result = await tool.execute(query="Find me", max_results=5)
    assert result.is_error is False
    assert result.content.count("## Match") <= 5


async def test_no_matches_returns_friendly_message(tool: SearchHistoryTool):
    result = await tool.execute(query="nonexistent")
    assert result.is_error is False
    assert "No matches found" in result.content


async def test_tool_calls_excluded_from_search(memory: JsonlMemory, tool: SearchHistoryTool):
    from squidbot.core.models import ToolCall

    await memory.append_message("cli:local", Message(role="user", content="Search for secrets"))
    await memory.append_message(
        "cli:local",
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="tc1", name="read_file", arguments={"path": "/etc/secrets"})],
        ),
    )
    await memory.append_message(
        "cli:local", Message(role="tool", content="secret data here", tool_call_id="tc1")
    )

    result = await tool.execute(query="secrets")
    assert result.is_error is False
    assert "Search for secrets" in result.content
    assert "secret data here" not in result.content


async def test_context_includes_surrounding_messages(memory: JsonlMemory, tool: SearchHistoryTool):
    await memory.append_message("cli:local", Message(role="user", content="Before context."))
    await memory.append_message("cli:local", Message(role="user", content="Target keyword here."))
    await memory.append_message(
        "cli:local", Message(role="assistant", content="After context response.")
    )

    result = await tool.execute(query="Target keyword")
    assert result.is_error is False
    assert "Before context" in result.content
    assert "After context response" in result.content


async def test_query_required(tool: SearchHistoryTool):
    result = await tool.execute()
    assert result.is_error is True
    assert "query is required" in result.content.lower()


async def test_tool_call_messages_are_searchable(memory: JsonlMemory, tool: SearchHistoryTool):
    """tool_call messages with matching content appear in search results."""
    await memory.append_message(
        "cli:local",
        Message(role="tool_call", content="shell(cmd='git log --oneline')"),
    )
    result = await tool.execute(query="git log")
    assert result.is_error is False
    assert "git log" in result.content


async def test_tool_result_messages_are_searchable(memory: JsonlMemory, tool: SearchHistoryTool):
    """tool_result messages with matching content appear in search results."""
    await memory.append_message(
        "cli:local",
        Message(role="tool_result", content="abc1234 fix: typo in README"),
    )
    result = await tool.execute(query="fix: typo")
    assert result.is_error is False
    assert "fix: typo" in result.content


async def test_tool_call_shown_with_tool_call_label(memory: JsonlMemory, tool: SearchHistoryTool):
    """Matching tool_call messages display with 'TOOL CALL' label."""
    await memory.append_message(
        "cli:local",
        Message(role="tool_call", content="read_file(path='/tmp/notes.txt')"),
    )
    result = await tool.execute(query="notes.txt")
    assert "TOOL CALL" in result.content


async def test_tool_result_shown_with_tool_result_label(
    memory: JsonlMemory, tool: SearchHistoryTool
):
    """Matching tool_result messages display with 'TOOL RESULT' label."""
    await memory.append_message(
        "cli:local",
        Message(role="tool_result", content="contents of notes"),
    )
    result = await tool.execute(query="contents of notes")
    assert "TOOL RESULT" in result.content


async def test_tool_events_appear_as_context_for_surrounding_match(
    memory: JsonlMemory, tool: SearchHistoryTool
):
    """tool_call/tool_result adjacent to a matching user message appear as context."""
    await memory.append_message("cli:local", Message(role="user", content="Run git status please"))
    await memory.append_message(
        "cli:local", Message(role="tool_call", content="shell(cmd='git status')")
    )
    await memory.append_message(
        "cli:local", Message(role="tool_result", content="On branch main, nothing to commit")
    )
    result = await tool.execute(query="git status")
    assert result.is_error is False
    # The user message matched, and tool_call/tool_result appear as context
    assert "git status" in result.content.lower()
    assert "TOOL CALL" in result.content
    assert "TOOL RESULT" in result.content
