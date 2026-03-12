"""Tests for context builder."""

import pytest
from pathlib import Path

from fagent.agent.context import ContextBuilder


def test_context_builder_init(tmp_path):
    """Test context builder initialization."""
    builder = ContextBuilder(tmp_path)
    assert builder.workspace == tmp_path


def test_build_system_prompt_basic(tmp_path):
    """Test building basic system prompt."""
    builder = ContextBuilder(tmp_path)
    prompt = builder.build_system_prompt()

    assert "fagent" in prompt
    assert str(tmp_path) in prompt
    assert "workspace" in prompt.lower()


def test_build_system_prompt_with_shadow(tmp_path):
    """Test system prompt with shadow context."""
    builder = ContextBuilder(tmp_path)
    shadow = "Previous conversation summary"
    prompt = builder.build_system_prompt(shadow_context=shadow)

    assert "Shadow Context" in prompt
    assert shadow in prompt


def test_build_system_prompt_with_memory(tmp_path):
    """Test system prompt with runtime memory."""
    builder = ContextBuilder(tmp_path)
    memory = "Key facts from memory"
    prompt = builder.build_system_prompt(runtime_memory_context=memory)

    assert "Runtime Memory" in prompt or "Memory" in prompt
    assert memory in prompt


def test_build_system_prompt_with_bootstrap(tmp_path):
    """Test system prompt includes bootstrap files."""
    (tmp_path / "AGENTS.md").write_text("# Agent config")
    (tmp_path / "SOUL.md").write_text("# Soul config")

    builder = ContextBuilder(tmp_path)
    prompt = builder.build_system_prompt()

    assert "Agent config" in prompt
    assert "Soul config" in prompt


def test_build_messages_basic(tmp_path):
    """Test building message list."""
    builder = ContextBuilder(tmp_path)
    messages = builder.build_messages(
        history=[],
        current_message="Hello"
    )

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "Hello" in messages[1]["content"]


def test_build_messages_with_history(tmp_path):
    """Test building messages with history."""
    builder = ContextBuilder(tmp_path)
    history = [
        {"role": "user", "content": "First message"},
        {"role": "assistant", "content": "First response"},
    ]

    messages = builder.build_messages(history, "Second message")

    assert len(messages) == 4
    assert messages[1] == history[0]
    assert messages[2] == history[1]


def test_build_messages_with_media(tmp_path):
    """Test building messages with media."""
    img_file = tmp_path / "test.png"
    # Create minimal PNG
    img_file.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)

    builder = ContextBuilder(tmp_path)
    messages = builder.build_messages(
        history=[],
        current_message="Check image",
        media=[str(img_file)]
    )

    user_content = messages[1]["content"]
    assert isinstance(user_content, list)
    assert any(item.get("type") == "image_url" for item in user_content)


def test_build_messages_runtime_context(tmp_path):
    """Test runtime context is included."""
    builder = ContextBuilder(tmp_path)
    messages = builder.build_messages(
        history=[],
        current_message="Test",
        channel="telegram",
        chat_id="123"
    )

    user_content = messages[1]["content"]
    assert "telegram" in user_content.lower() or "123" in user_content


def test_add_tool_result(tmp_path):
    """Test adding tool result."""
    builder = ContextBuilder(tmp_path)
    messages = [{"role": "user", "content": "test"}]

    updated = builder.add_tool_result(
        messages, "call_123", "read_file", "file content"
    )

    assert len(updated) == 2
    assert updated[1]["role"] == "tool"
    assert updated[1]["tool_call_id"] == "call_123"
    assert updated[1]["content"] == "file content"


def test_add_assistant_message(tmp_path):
    """Test adding assistant message."""
    builder = ContextBuilder(tmp_path)
    messages = [{"role": "user", "content": "test"}]

    updated = builder.add_assistant_message(
        messages, "Response text"
    )

    assert len(updated) == 2
    assert updated[1]["role"] == "assistant"
    assert updated[1]["content"] == "Response text"


def test_add_assistant_message_with_tools(tmp_path):
    """Test adding assistant message with tool calls."""
    builder = ContextBuilder(tmp_path)
    messages = []

    tool_calls = [{"id": "call_1", "type": "function", "function": {"name": "test"}}]
    updated = builder.add_assistant_message(
        messages, "Calling tool", tool_calls=tool_calls
    )

    assert updated[0]["tool_calls"] == tool_calls
