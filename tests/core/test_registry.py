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


def test_get_definitions_caching():
    registry = ToolRegistry()
    registry.register(EchoTool())

    # First call builds cache
    defs1 = registry.get_definitions()
    # Second call uses cache
    defs2 = registry.get_definitions()

    assert defs1 == defs2
    assert defs1 is not defs2  # Should be a new list copy

    # Mutation of returned list doesn't affect cache
    defs1.clear()
    assert len(registry.get_definitions()) == 1

    # Invalidation on register
    class AnotherTool:
        name = "another"
        description = "Another tool"
        parameters = {"type": "object", "properties": {}}

    registry.register(AnotherTool())
    defs3 = registry.get_definitions()
    assert len(defs3) == 2
    assert any(d.name == "another" for d in defs3)
