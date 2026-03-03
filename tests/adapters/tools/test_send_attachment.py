"""Tests for SendAttachmentTool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from squidbot.core.models import OutboundMessage, Session


def _make_session() -> Session:
    return Session(channel="matrix", sender_id="@alice:example.org")


def _make_tool(
    *,
    channel: _CollectingChannel,
    workspace: Path,
    outbound_metadata: dict[str, Any] | None = None,
    restrict_to_workspace: bool = False,
):
    from squidbot.adapters.tools.files import SendAttachmentTool

    return SendAttachmentTool(
        channel=channel,  # type: ignore[arg-type]
        session=_make_session(),
        outbound_metadata=outbound_metadata or {},
        workspace=workspace,
        restrict_to_workspace=restrict_to_workspace,
    )


class _CollectingChannel:
    """Test double that records sent OutboundMessages."""

    streaming: bool = False

    def __init__(self) -> None:
        self.sent: list[OutboundMessage] = []

    async def send(self, message: OutboundMessage) -> None:
        self.sent.append(message)

    async def send_typing(self, session_id: str, typing: bool = True) -> None:
        pass


class _FailingChannel(_CollectingChannel):
    """Test double that raises during send()."""

    async def send(self, message: OutboundMessage) -> None:
        raise RuntimeError("send failed")


class TestSendAttachmentToolMissingPath:
    """SendAttachmentTool returns an error when path is missing or invalid."""

    async def test_no_path_returns_error(self) -> None:
        channel = _CollectingChannel()
        tool = _make_tool(channel=channel, workspace=Path("."))
        result = await tool.execute()
        assert result.is_error
        assert "path" in result.content.lower()

    async def test_path_none_returns_error(self) -> None:
        channel = _CollectingChannel()
        tool = _make_tool(channel=channel, workspace=Path("."))
        result = await tool.execute(path=None)
        assert result.is_error
        assert "path" in result.content.lower()


class TestSendAttachmentToolMissingFile:
    """SendAttachmentTool returns an error when the file does not exist."""

    async def test_nonexistent_file_returns_error(self, tmp_path: Path) -> None:
        channel = _CollectingChannel()
        tool = _make_tool(channel=channel, workspace=tmp_path)
        result = await tool.execute(path=str(tmp_path / "nonexistent.txt"))
        assert result.is_error
        assert "not found" in result.content.lower() or "does not exist" in result.content.lower()


class TestSendAttachmentToolPathSafety:
    """SendAttachmentTool follows workspace safety rules."""

    async def test_relative_path_resolves_against_workspace(self, tmp_path: Path) -> None:
        file = tmp_path / "note.txt"
        file.write_text("ok", encoding="utf-8")
        channel = _CollectingChannel()
        tool = _make_tool(channel=channel, workspace=tmp_path)

        result = await tool.execute(path="note.txt")

        assert not result.is_error
        assert channel.sent[0].attachment == file

    async def test_outside_workspace_is_blocked_when_restricted(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        channel = _CollectingChannel()
        tool = _make_tool(channel=channel, workspace=tmp_path, restrict_to_workspace=True)

        result = await tool.execute(path=str(outside))

        assert result.is_error
        assert "outside workspace" in result.content.lower()

    async def test_directory_path_returns_error(self, tmp_path: Path) -> None:
        folder = tmp_path / "folder"
        folder.mkdir()
        channel = _CollectingChannel()
        tool = _make_tool(channel=channel, workspace=tmp_path)

        result = await tool.execute(path=str(folder))

        assert result.is_error
        assert "not a file" in result.content.lower()


class TestSendAttachmentToolSendsFile:
    """SendAttachmentTool sends a real file as an OutboundMessage attachment."""

    async def test_sends_file_as_attachment(self, tmp_path: Path) -> None:
        file = tmp_path / "data.txt"
        file.write_text("hello", encoding="utf-8")

        channel = _CollectingChannel()
        tool = _make_tool(
            channel=channel,
            workspace=tmp_path,
            outbound_metadata={"matrix_room_id": "!room:example.org"},
        )
        result = await tool.execute(path=str(file))

        assert not result.is_error
        assert len(channel.sent) == 1
        sent = channel.sent[0]
        assert sent.attachment == file
        assert sent.session == _make_session()
        assert sent.metadata.get("matrix_room_id") == "!room:example.org"

    async def test_success_result_contains_filename(self, tmp_path: Path) -> None:
        file = tmp_path / "report.pdf"
        file.write_bytes(b"%PDF")

        channel = _CollectingChannel()
        tool = _make_tool(channel=channel, workspace=tmp_path)
        result = await tool.execute(path=str(file))

        assert not result.is_error
        assert "report.pdf" in result.content

    async def test_metadata_propagated_to_sent_message(self, tmp_path: Path) -> None:
        file = tmp_path / "img.png"
        file.write_bytes(b"\x89PNG")

        meta: dict[str, Any] = {
            "matrix_room_id": "!abc:example.org",
            "matrix_thread_root": "$evt123",
        }
        channel = _CollectingChannel()
        tool = _make_tool(channel=channel, workspace=tmp_path, outbound_metadata=meta)
        await tool.execute(path=str(file))

        sent = channel.sent[0]
        assert sent.metadata["matrix_thread_root"] == "$evt123"

    async def test_channel_send_exception_returns_tool_error(self, tmp_path: Path) -> None:
        file = tmp_path / "err.txt"
        file.write_text("x", encoding="utf-8")

        channel = _FailingChannel()
        tool = _make_tool(channel=channel, workspace=tmp_path)
        result = await tool.execute(path=str(file))

        assert result.is_error
        assert "failed to send attachment" in result.content.lower()


class TestSendAttachmentToolDefinition:
    """SendAttachmentTool exposes the correct ToolPort interface."""

    def test_name(self) -> None:
        channel = _CollectingChannel()
        tool = _make_tool(channel=channel, workspace=Path("."))
        assert tool.name == "send_attachment"

    def test_parameters_require_path(self) -> None:
        channel = _CollectingChannel()
        tool = _make_tool(channel=channel, workspace=Path("."))
        assert "path" in tool.parameters["properties"]
        assert "path" in tool.parameters.get("required", [])
