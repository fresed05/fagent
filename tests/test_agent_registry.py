"""Tests for agent registry."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from fagent.agent.registry import AgentRegistry, AgentInfo
from fagent.bus.queue import MessageBus
from fagent.config.schema import AgentConfig


@pytest.fixture
def mock_bus():
    """Mock message bus."""
    bus = Mock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return bus


@pytest.fixture
def registry(tmp_path, mock_bus):
    """Create agent registry."""
    return AgentRegistry(bus=mock_bus, workspace=tmp_path)


def test_register_agent(registry):
    """Test registering a new agent."""
    config = AgentConfig(model="test-model")
    agent_id = registry.register_agent("test-agent", "test-model", config)

    assert agent_id is not None
    assert len(agent_id) == 8
    agent = registry.get_agent(agent_id)
    assert agent is not None
    assert agent.name == "test-agent"
    assert agent.model == "test-model"


def test_get_agent(registry):
    """Test getting agent by ID."""
    config = AgentConfig(model="test-model")
    agent_id = registry.register_agent("test", "test-model", config)

    agent = registry.get_agent(agent_id)
    assert agent is not None
    assert agent.agent_id == agent_id


def test_get_nonexistent_agent(registry):
    """Test getting non-existent agent returns None."""
    agent = registry.get_agent("nonexistent")
    assert agent is None


def test_list_agents(registry):
    """Test listing all agents."""
    config = AgentConfig(model="model1")
    registry.register_agent("agent1", "model1", config)
    registry.register_agent("agent2", "model2", config)

    agents = registry.list_agents()
    assert len(agents) == 2
    assert all(isinstance(a, AgentInfo) for a in agents)


def test_remove_agent(registry):
    """Test removing an agent."""
    config = AgentConfig(model="test-model")
    agent_id = registry.register_agent("test", "test-model", config)

    result = registry.remove_agent(agent_id)
    assert result is True
    assert registry.get_agent(agent_id) is None


def test_remove_nonexistent_agent(registry):
    """Test removing non-existent agent returns False."""
    result = registry.remove_agent("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_send_message_to_agent(registry, mock_bus):
    """Test sending message to agent."""
    config = AgentConfig(model="test-model")
    agent_id = registry.register_agent("test", "test-model", config)

    success = await registry.send_message_to_agent(agent_id, "Hello")
    assert success is True
    mock_bus.publish_inbound.assert_called_once()


@pytest.mark.asyncio
async def test_send_message_to_nonexistent_agent(registry, mock_bus):
    """Test sending message to non-existent agent fails."""
    success = await registry.send_message_to_agent("nonexistent", "Hello")
    assert success is False
    mock_bus.publish_inbound.assert_not_called()
