"""Tests for filesystem tools."""

import pytest
from pathlib import Path

from fagent.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool


@pytest.mark.asyncio
async def test_read_file_success(tmp_path):
    """Test reading a file."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello world")

    tool = ReadFileTool(workspace=tmp_path)
    result = await tool.execute("test.txt")
    assert "hello world" in result


@pytest.mark.asyncio
async def test_read_file_not_found(tmp_path):
    """Test reading non-existent file."""
    tool = ReadFileTool(workspace=tmp_path)
    result = await tool.execute("missing.txt")
    assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_read_file_truncation(tmp_path):
    """Test large file truncation."""
    test_file = tmp_path / "large.txt"
    test_file.write_text("x" * 200000)

    tool = ReadFileTool(workspace=tmp_path)
    result = await tool.execute("large.txt")
    assert "truncated" in result.lower()


@pytest.mark.asyncio
async def test_read_file_allowed_dir(tmp_path):
    """Test directory restriction."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("content")

    tool = ReadFileTool(workspace=tmp_path, allowed_dir=tmp_path)
    result = await tool.execute("test.txt")
    assert "content" in result

    # Try to read outside allowed dir
    result = await tool.execute("../outside.txt")
    assert "error" in result.lower() or "outside" in result.lower()


@pytest.mark.asyncio
async def test_write_file_success(tmp_path):
    """Test writing a file."""
    tool = WriteFileTool(workspace=tmp_path)
    result = await tool.execute("new.txt", "test content")
    assert "success" in result.lower()

    assert (tmp_path / "new.txt").read_text() == "test content"


@pytest.mark.asyncio
async def test_write_file_creates_dirs(tmp_path):
    """Test writing creates parent directories."""
    tool = WriteFileTool(workspace=tmp_path)
    result = await tool.execute("sub/dir/file.txt", "content")
    assert "success" in result.lower()
    assert (tmp_path / "sub/dir/file.txt").exists()


@pytest.mark.asyncio
async def test_write_file_allowed_dir(tmp_path):
    """Test write respects allowed directory."""
    tool = WriteFileTool(workspace=tmp_path, allowed_dir=tmp_path)
    result = await tool.execute("../outside.txt", "content")
    assert "error" in result.lower() or "outside" in result.lower()


@pytest.mark.asyncio
async def test_edit_file_success(tmp_path):
    """Test editing a file."""
    test_file = tmp_path / "edit.txt"
    test_file.write_text("hello world")

    tool = EditFileTool(workspace=tmp_path)
    result = await tool.execute("edit.txt", "world", "python")
    assert "success" in result.lower()
    assert test_file.read_text() == "hello python"


@pytest.mark.asyncio
async def test_edit_file_not_found(tmp_path):
    """Test editing non-existent file."""
    tool = EditFileTool(workspace=tmp_path)
    result = await tool.execute("missing.txt", "old", "new")
    assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_edit_file_text_not_found(tmp_path):
    """Test editing with non-matching text."""
    test_file = tmp_path / "edit.txt"
    test_file.write_text("hello world")

    tool = EditFileTool(workspace=tmp_path)
    result = await tool.execute("edit.txt", "missing", "new")
    assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_edit_file_multiple_occurrences(tmp_path):
    """Test editing warns on multiple matches."""
    test_file = tmp_path / "edit.txt"
    test_file.write_text("test test test")

    tool = EditFileTool(workspace=tmp_path)
    result = await tool.execute("edit.txt", "test", "new")
    assert "appears" in result.lower() and "times" in result.lower()


@pytest.mark.asyncio
async def test_list_dir_success(tmp_path):
    """Test listing directory."""
    (tmp_path / "file1.txt").touch()
    (tmp_path / "file2.txt").touch()
    (tmp_path / "subdir").mkdir()

    tool = ListDirTool(workspace=tmp_path)
    result = await tool.execute(".")
    assert "file1.txt" in result
    assert "file2.txt" in result
    assert "subdir" in result


@pytest.mark.asyncio
async def test_list_dir_empty(tmp_path):
    """Test listing empty directory."""
    tool = ListDirTool(workspace=tmp_path)
    result = await tool.execute(".")
    assert "empty" in result.lower()


@pytest.mark.asyncio
async def test_list_dir_not_found(tmp_path):
    """Test listing non-existent directory."""
    tool = ListDirTool(workspace=tmp_path)
    result = await tool.execute("missing")
    assert "not found" in result.lower()
