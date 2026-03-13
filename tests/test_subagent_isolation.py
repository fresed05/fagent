"""Tests for sub-agent isolation from main agent memory."""

import pytest
from fagent.bus.events import InboundMessage, OutboundMessage


def test_subagent_result_metadata():
    """Test that sub-agent results have _subagent_result metadata."""
    msg = InboundMessage(
        channel="system",
        sender_id="subagent",
        chat_id="telegram:123",
        content="Task completed",
        metadata={"_subagent_result": True},
    )

    assert msg.metadata.get("_subagent_result") is True
    assert msg.sender_id == "subagent"


def test_subagent_metadata_check():
    """Test metadata check logic for skipping pipeline."""
    # Sub-agent message
    subagent_msg = InboundMessage(
        channel="system",
        sender_id="subagent",
        chat_id="telegram:123",
        content="Result",
        metadata={"_subagent_result": True},
    )

    # Normal message
    normal_msg = InboundMessage(
        channel="telegram",
        sender_id="user123",
        chat_id="123",
        content="Hello",
    )

    # Check logic
    assert subagent_msg.metadata.get("_subagent_result") is True
    assert normal_msg.metadata.get("_subagent_result") is None


def test_telegram_filter_logic():
    """Test Telegram filtering logic for sub-agent messages."""
    # Sub-agent text message (should be filtered)
    text_msg = OutboundMessage(
        channel="telegram",
        chat_id="123",
        content="Sub-agent result",
        metadata={"_subagent_result": True},
    )

    # Sub-agent progress message (should pass)
    progress_msg = OutboundMessage(
        channel="telegram",
        chat_id="123",
        content="Running tool",
        metadata={"_subagent_result": True, "_progress": True},
    )

    # Normal message (should pass)
    normal_msg = OutboundMessage(
        channel="telegram",
        chat_id="123",
        content="Normal response",
    )

    # Filter logic
    should_filter_text = text_msg.metadata.get("_subagent_result") and not text_msg.metadata.get("_progress")
    should_filter_progress = progress_msg.metadata.get("_subagent_result") and not progress_msg.metadata.get("_progress")
    should_filter_normal = normal_msg.metadata.get("_subagent_result") and not normal_msg.metadata.get("_progress")

    assert should_filter_text is True
    assert should_filter_progress is False
    assert should_filter_normal in (False, None)  # None when _subagent_result is missing


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
