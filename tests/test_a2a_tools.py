"""Tests for A2A protocol tools."""

import pytest
from unittest.mock import AsyncMock, Mock

from fagent.agent.registry import AgentRegistry
from fagent.agent.tools.create_agent import CreateAgentTool
from fagent.agent.tools.send_to_agent import SendToAgentTool
from fagent.agent.tools.list_agents import ListAgentsTool
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


@pytest.mark.asyncio
async def test_create_agent_tool(registry):
    """Test create_agent tool."""
    tool = CreateAgentTool(registry)

    result = await tool.execute(name="test-agent", model="test-model")

    assert "created successfully" in result
    agents = registry.list_agents()
    assert len(agents) == 1
    assert agents[0].name == "test-agent"


@pytest.mark.asyncio
async def test_send_to_agent_tool(registry, mock_bus):
    """Test send_to_agent tool."""
    config = AgentConfig(model="test-model")
    agent_id = registry.register_agent("test", "test-model", config)

    tool = SendToAgentTool(registry)
    result = await tool.execute(agent_id=agent_id, message="Hello")

    assert "sent" in result.lower()
    mock_bus.publish_inbound.assert_called_once()


@pytest.mark.asyncio
async def test_send_to_nonexistent_agent(registry):
    """Test sending to non-existent agent."""
    tool = SendToAgentTool(registry)
    result = await tool.execute(agent_id="nonexistent", message="Hello")

    assert "failed" in result.lower() or "not found" in result.lower()


@pytest.mark.asyncio
async def test_list_agents_tool_empty(registry):
    """Test list_agents with no agents."""
    tool = ListAgentsTool(registry)
    result = await tool.execute()

    assert "no agents" in result.lower()


@pytest.mark.asyncio
async def test_list_agents_tool_with_agents(registry):
    """Test list_agents with registered agents."""
    config = AgentConfig(model="model1")
    registry.register_agent("agent1", "model1", config)
    registry.register_agent("agent2", "model2", config)

    tool = ListAgentsTool(registry)
    result = await tool.execute()

    assert "agent1" in result
    assert "agent2" in result
    assert "model1" in result
