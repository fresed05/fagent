"""Tests for tool registry."""

import pytest
from typing import Any

from fagent.agent.tools.base import Tool
from fagent.agent.tools.registry import ToolRegistry


class MockTool(Tool):
    """Mock tool for testing."""

    def __init__(self, tool_name: str = "mock"):
        self._name = tool_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Mock tool for testing"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "value": {"type": "string"},
                "count": {"type": "integer", "minimum": 1},
            },
            "required": ["value"],
        }

    async def execute(self, value: str, count: int = 1, **kwargs: Any) -> str:
        return f"{value} x {count}"


@pytest.mark.asyncio
async def test_registry_register():
    """Test registering a tool."""
    registry = ToolRegistry()
    tool = MockTool()
    registry.register(tool)

    assert registry.has("mock")
    assert len(registry) == 1
    assert "mock" in registry.tool_names


@pytest.mark.asyncio
async def test_registry_get():
    """Test getting a tool."""
    registry = ToolRegistry()
    tool = MockTool()
    registry.register(tool)

    retrieved = registry.get("mock")
    assert retrieved is tool


@pytest.mark.asyncio
async def test_registry_unregister():
    """Test unregistering a tool."""
    registry = ToolRegistry()
    tool = MockTool()
    registry.register(tool)

    registry.unregister("mock")
    assert not registry.has("mock")
    assert len(registry) == 0


@pytest.mark.asyncio
async def test_registry_execute_success():
    """Test executing a tool."""
    registry = ToolRegistry()
    registry.register(MockTool())

    result = await registry.execute("mock", {"value": "test", "count": 3})
    assert result == "test x 3"


@pytest.mark.asyncio
async def test_registry_execute_not_found():
    """Test executing non-existent tool."""
    registry = ToolRegistry()
    result = await registry.execute("missing", {})
    assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_registry_execute_missing_required():
    """Test executing with missing required parameter."""
    registry = ToolRegistry()
    registry.register(MockTool())

    result = await registry.execute("mock", {})
    assert "error" in result.lower()
    assert "value" in result.lower()


@pytest.mark.asyncio
async def test_registry_execute_invalid_type():
    """Test executing with invalid parameter type."""
    registry = ToolRegistry()
    registry.register(MockTool())

    result = await registry.execute("mock", {"value": "test", "count": "invalid"})
    # Should attempt to cast or return error
    assert "error" in result.lower() or "test" in result


@pytest.mark.asyncio
async def test_registry_get_definitions():
    """Test getting tool definitions."""
    registry = ToolRegistry()
    registry.register(MockTool("tool1"))
    registry.register(MockTool("tool2"))

    definitions = registry.get_definitions()
    assert len(definitions) == 2
    assert any(d["function"]["name"] == "tool1" for d in definitions)
    assert any(d["function"]["name"] == "tool2" for d in definitions)


@pytest.mark.asyncio
async def test_registry_contains():
    """Test __contains__ operator."""
    registry = ToolRegistry()
    registry.register(MockTool())

    assert "mock" in registry
    assert "missing" not in registry
