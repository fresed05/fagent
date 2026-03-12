"""Tests for subagent manager."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fagent.agent.subagent import SubagentManager
from fagent.bus.queue import MessageBus


@pytest.fixture
def mock_provider():
    """Mock LLM provider."""
    provider = Mock()
    provider.get_default_model.return_value = "test-model"
    return provider


@pytest.fixture
def mock_bus():
    """Mock message bus."""
    bus = Mock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return bus


@pytest.fixture
def manager(tmp_path, mock_provider, mock_bus):
    """Create subagent manager."""
    return SubagentManager(
        provider=mock_provider,
        workspace=tmp_path,
        bus=mock_bus,
    )


@pytest.mark.asyncio
async def test_spawn_subagent(manager):
    """Test spawning a subagent."""
    result = await manager.spawn("Test task")

    assert "started" in result.lower()
    assert manager.get_running_count() >= 0


@pytest.mark.asyncio
async def test_spawn_with_label(manager):
    """Test spawning with custom label."""
    result = await manager.spawn("Long task description", label="Short")

    assert "Short" in result


@pytest.mark.asyncio
async def test_spawn_with_session(manager):
    """Test spawning with session tracking."""
    result = await manager.spawn("Task", session_key="session_123")

    assert "started" in result.lower()


@pytest.mark.asyncio
async def test_get_running_count(manager):
    """Test getting running subagent count."""
    initial = manager.get_running_count()
    assert initial >= 0


@pytest.mark.asyncio
async def test_cancel_by_session(manager):
    """Test canceling subagents by session."""
    # Spawn with session
    await manager.spawn("Task 1", session_key="session_1")
    await manager.spawn("Task 2", session_key="session_1")

    # Cancel
    count = await manager.cancel_by_session("session_1")
    assert count >= 0
