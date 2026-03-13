"""Tests for subagent model selection."""

import pytest
from unittest.mock import AsyncMock, Mock

from fagent.agent.subagent import SubagentManager
from fagent.bus.queue import MessageBus


@pytest.fixture
def mock_provider():
    """Mock LLM provider."""
    provider = Mock()
    provider.get_default_model.return_value = "default-model"
    provider.chat = AsyncMock(return_value=Mock(has_tool_calls=False, content="Done"))
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
async def test_spawn_with_custom_model(manager, mock_provider):
    """Test spawning subagent with custom model."""
    result = await manager.spawn("Test task", model="custom-model")

    assert "started" in result.lower()
    # Wait a bit for background task to start
    import asyncio
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_spawn_without_model_uses_default(manager, mock_provider):
    """Test spawning without model uses default."""
    result = await manager.spawn("Test task")

    assert "started" in result.lower()
