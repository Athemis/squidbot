import pytest
from squidbot.core.models import ToolResult
from squidbot.core.registry import ToolRegistry


class EchoTool:
    name = "echo"
    description = "Echoes the input"
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, text: str, **_) -> ToolResult:
        return ToolResult(tool_call_id="", content=text)


def test_register_and_list():
    registry = ToolRegistry()
    registry.register(EchoTool())
    definitions = registry.get_definitions()
    assert len(definitions) == 1
    assert definitions[0].name == "echo"


async def test_execute_known_tool():
    registry = ToolRegistry()
    registry.register(EchoTool())
    result = await registry.execute("echo", tool_call_id="tc_1", text="hello")
    assert result.content == "hello"
    assert result.tool_call_id == "tc_1"


async def test_execute_unknown_tool_returns_error():
    registry = ToolRegistry()
    result = await registry.execute("unknown_tool", tool_call_id="tc_1")
    assert result.is_error is True
    assert "unknown_tool" in result.content
