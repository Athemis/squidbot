from __future__ import annotations

from datetime import datetime

from squidbot.core.models import (
    ChannelStatus,
    CronJob,
    InboundMessage,
    Message,
    OutboundMessage,
    Session,
    SessionInfo,
    ToolCall,
    ToolDefinition,
)


def test_message_basic():
    msg = Message(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"
    assert isinstance(msg.timestamp, datetime)


def test_message_with_tool_call():
    tool_call = ToolCall(id="tc_1", name="shell", arguments={"command": "ls"})
    msg = Message(role="assistant", content="", tool_calls=[tool_call])
    assert msg.tool_calls[0].name == "shell"


def test_session_id_format():
    session = Session(channel="cli", sender_id="local")
    assert session.id == "cli:local"


def test_cron_job_defaults():
    job = CronJob(
        id="j1", name="daily", message="good morning", schedule="0 9 * * *", channel="cli:local"
    )
    assert job.enabled is True
    assert job.last_run is None
    assert job.timezone == "UTC"
    assert job.channel == "cli:local"


def test_tool_definition():
    tool = ToolDefinition(
        name="shell",
        description="Run a shell command",
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    )
    assert tool.name == "shell"


def test_inbound_message_metadata_default_empty():
    session = Session(channel="test", sender_id="user")
    msg = InboundMessage(session=session, text="hello")
    assert msg.metadata == {}


def test_inbound_message_metadata_custom():
    session = Session(channel="test", sender_id="user")
    msg = InboundMessage(session=session, text="hi", metadata={"matrix_event_id": "$abc"})
    assert msg.metadata["matrix_event_id"] == "$abc"


def test_outbound_message_attachment_default_none():
    session = Session(channel="test", sender_id="user")
    msg = OutboundMessage(session=session, text="hi")
    assert msg.attachment is None
    assert msg.metadata == {}


def test_outbound_message_attachment_set():
    from pathlib import Path

    session = Session(channel="test", sender_id="user")
    msg = OutboundMessage(session=session, text="", attachment=Path("/tmp/foo.jpg"))
    assert msg.attachment == Path("/tmp/foo.jpg")


class TestSessionInfo:
    def test_fields(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0)
        info = SessionInfo(
            session_id="matrix:@alice:example.com",
            channel="matrix",
            sender_id="@alice:example.com",
            started_at=now,
            message_count=3,
        )
        assert info.session_id == "matrix:@alice:example.com"
        assert info.channel == "matrix"
        assert info.sender_id == "@alice:example.com"
        assert info.started_at == now
        assert info.message_count == 3


class TestChannelStatus:
    def test_connected_with_no_error(self) -> None:
        status = ChannelStatus(name="matrix", enabled=True, connected=True)
        assert status.name == "matrix"
        assert status.enabled is True
        assert status.connected is True
        assert status.error is None

    def test_error_field(self) -> None:
        status = ChannelStatus(name="email", enabled=True, connected=False, error="timeout")
        assert status.error == "timeout"
        assert status.connected is False
