"""Tests for agent configuration."""

import pytest
from fagent.config.schema import AgentConfig, AgentDefaults, AgentsConfig


def test_agent_config_defaults():
    """Test agent config with defaults."""
    config = AgentConfig()
    assert config.model is None
    assert config.temperature is None
    assert config.disable_vector_memory is False
    assert config.disable_shadow_context is False


def test_agent_config_with_values():
    """Test agent config with custom values."""
    config = AgentConfig(
        model="test-model",
        temperature=0.5,
        max_tokens=1000,
        disable_vector_memory=True,
    )
    assert config.model == "test-model"
    assert config.temperature == 0.5
    assert config.max_tokens == 1000
    assert config.disable_vector_memory is True


def test_agents_config_defaults():
    """Test agents config with defaults."""
    config = AgentsConfig()
    assert isinstance(config.defaults, AgentDefaults)
    assert config.agents == {}


def test_agents_config_with_agents():
    """Test agents config with multiple agents."""
    agent1 = AgentConfig(model="model1")
    agent2 = AgentConfig(model="model2")

    config = AgentsConfig(agents={"agent1": agent1, "agent2": agent2})
    assert len(config.agents) == 2
    assert "agent1" in config.agents
    assert "agent2" in config.agents
