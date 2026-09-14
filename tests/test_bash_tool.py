import pytest

from tools.bash_tool import BashTool


@pytest.mark.asyncio
async def test_execute_runs_a_harmless_command_and_returns_its_output():
    tool = BashTool()
    result = await tool.execute("echo hello")
    assert result["blocked"] is False
    assert result["stdout"].strip() == "hello"
    assert result["exit_code"] == 0


@pytest.mark.asyncio
async def test_execute_defaults_cwd_to_tmp_not_the_read_only_lambda_task_dir():
    """/var/task (the deployed Lambda package, the process's actual cwd) is
    read-only at runtime — a command with no explicit cwd override used to
    inherit that and fail on any write. /tmp is the one writable directory
    every standard Lambda runtime provides."""
    tool = BashTool()
    result = await tool.execute("pwd")
    assert result["stdout"].strip() == "/tmp"


@pytest.mark.asyncio
async def test_execute_honors_an_explicit_cwd_override():
    tool = BashTool()
    result = await tool.execute("pwd", cwd="/")
    assert result["stdout"].strip() == "/"


@pytest.mark.asyncio
async def test_execute_blocks_a_dangerous_command_without_running_it():
    tool = BashTool()
    result = await tool.execute("rm -rf /")
    assert result["blocked"] is True
    assert "no_rm_rf" in result["failed_checks"]


@pytest.mark.asyncio
async def test_execute_blocks_sudo():
    tool = BashTool()
    result = await tool.execute("sudo apt-get install x")
    assert result["blocked"] is True
    assert "no_sudo" in result["failed_checks"]


@pytest.mark.asyncio
async def test_execute_captures_stderr_and_nonzero_exit_code():
    tool = BashTool()
    result = await tool.execute("ls /this-does-not-exist-anywhere")
    assert result["blocked"] is False
    assert result["exit_code"] != 0
    assert result["stderr"]


@pytest.mark.asyncio
async def test_execute_times_out_a_hanging_command():
    tool = BashTool()
    result = await tool.execute("sleep 5", timeout=1)
    assert result["blocked"] is False
    assert "timed out" in result["error"]
