from datetime import datetime
from squidbot.core.models import Message, Session, CronJob, ToolCall, ToolDefinition


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
