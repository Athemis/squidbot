
import pytest

from squidbot.adapters.tools.files import ListFilesTool, ReadFileTool, WriteFileTool
from squidbot.adapters.tools.shell import ShellTool


@pytest.fixture
def tmp_workspace(tmp_path):
    return tmp_path


async def test_shell_runs_command():
    tool = ShellTool(workspace=None, restrict_to_workspace=False)
    result = await tool.execute(command="echo hello")
    assert "hello" in result.content
    assert result.is_error is False


async def test_shell_captures_stderr():
    tool = ShellTool(workspace=None, restrict_to_workspace=False)
    result = await tool.execute(command="ls /nonexistent_path_xyz")
    assert result.is_error is True


async def test_read_file(tmp_workspace):
    (tmp_workspace / "test.txt").write_text("hello content")
    tool = ReadFileTool(workspace=tmp_workspace, restrict_to_workspace=True)
    result = await tool.execute(path="test.txt")
    assert "hello content" in result.content
    assert result.is_error is False


async def test_read_file_outside_workspace_blocked(tmp_workspace):
    tool = ReadFileTool(workspace=tmp_workspace, restrict_to_workspace=True)
    result = await tool.execute(path="/etc/passwd")
    assert result.is_error is True
    assert "outside workspace" in result.content.lower()


async def test_write_file(tmp_workspace):
    tool = WriteFileTool(workspace=tmp_workspace, restrict_to_workspace=True)
    result = await tool.execute(path="output.txt", content="written content")
    assert result.is_error is False
    assert (tmp_workspace / "output.txt").read_text() == "written content"


async def test_list_files(tmp_workspace):
    (tmp_workspace / "a.txt").write_text("a")
    (tmp_workspace / "b.txt").write_text("b")
    tool = ListFilesTool(workspace=tmp_workspace, restrict_to_workspace=True)
    result = await tool.execute(path=".")
    assert "a.txt" in result.content
    assert "b.txt" in result.content
