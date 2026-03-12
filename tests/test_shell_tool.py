"""Tests for shell execution tool."""

import asyncio
import pytest
from pathlib import Path

from fagent.agent.tools.shell import ExecTool


@pytest.mark.asyncio
async def test_exec_simple_command():
    """Test executing a simple command."""
    tool = ExecTool(timeout=5)
    result = await tool.execute("echo hello")
    assert "hello" in result.lower()


@pytest.mark.asyncio
async def test_exec_with_working_dir(tmp_path):
    """Test command execution with custom working directory."""
    tool = ExecTool(working_dir=str(tmp_path))
    result = await tool.execute("pwd")
    assert str(tmp_path) in result or "tmp" in result


@pytest.mark.asyncio
async def test_exec_timeout():
    """Test command timeout."""
    tool = ExecTool(timeout=1)
    result = await tool.execute("sleep 5")
    assert "timed out" in result.lower()


@pytest.mark.asyncio
async def test_exec_stderr_capture():
    """Test stderr is captured."""
    tool = ExecTool()
    result = await tool.execute("python -c 'import sys; sys.stderr.write(\"error\")'")
    assert "STDERR" in result or "error" in result


@pytest.mark.asyncio
async def test_exec_nonzero_exit():
    """Test non-zero exit code is reported."""
    tool = ExecTool()
    result = await tool.execute("python -c 'import sys; sys.exit(1)'")
    assert "Exit code: 1" in result


@pytest.mark.asyncio
async def test_exec_deny_rm_rf():
    """Test dangerous rm -rf is blocked."""
    tool = ExecTool()
    result = await tool.execute("rm -rf /")
    assert "blocked" in result.lower() or "error" in result.lower()


@pytest.mark.asyncio
async def test_exec_deny_format():
    """Test format command is blocked."""
    tool = ExecTool()
    result = await tool.execute("format c:")
    assert "blocked" in result.lower() or "error" in result.lower()


@pytest.mark.asyncio
async def test_exec_allow_patterns():
    """Test allow patterns whitelist."""
    tool = ExecTool(allow_patterns=[r"^echo"])
    result = await tool.execute("echo test")
    assert "test" in result

    result = await tool.execute("ls")
    assert "blocked" in result.lower()


@pytest.mark.asyncio
async def test_exec_restrict_to_workspace(tmp_path):
    """Test workspace restriction."""
    tool = ExecTool(working_dir=str(tmp_path), restrict_to_workspace=True)

    # Path traversal should be blocked
    result = await tool.execute("cat ../etc/passwd")
    assert "blocked" in result.lower()


@pytest.mark.asyncio
async def test_exec_output_truncation():
    """Test very long output is truncated."""
    tool = ExecTool()
    # Generate >10000 chars
    result = await tool.execute("python -c 'print(\"x\" * 15000)'")
    assert "truncated" in result.lower() or len(result) < 12000


@pytest.mark.asyncio
async def test_exec_tool_schema():
    """Test tool schema is valid."""
    tool = ExecTool()
    assert tool.name == "exec"
    assert "command" in tool.parameters["properties"]
    assert "command" in tool.parameters["required"]
