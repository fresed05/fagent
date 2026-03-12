"""Tests for memory router."""

import pytest
from unittest.mock import Mock, AsyncMock

from fagent.memory.router import MemoryRouter


@pytest.fixture
def mock_provider():
    """Mock LLM provider."""
    provider = Mock()
    provider.embed = AsyncMock(return_value=[0.1] * 768)
    return provider


@pytest.fixture
def router(mock_provider):
    """Create memory router."""
    return MemoryRouter(provider=mock_provider)


@pytest.mark.asyncio
async def test_router_init(router):
    """Test router initialization."""
    assert router is not None


@pytest.mark.asyncio
async def test_route_temporal_query(router):
    """Test routing temporal query."""
    result = await router.route("what happened yesterday", "session_1")
    assert result is not None
    assert hasattr(result, 'intent')


@pytest.mark.asyncio
async def test_route_relationship_query(router):
    """Test routing relationship query."""
    result = await router.route("how is X related to Y", "session_1")
    assert result is not None
    assert hasattr(result, 'intent')


@pytest.mark.asyncio
async def test_route_factual_query(router):
    """Test routing factual query."""
    result = await router.route("what do you remember about the API", "session_1")
    assert result is not None
    assert hasattr(result, 'intent')
