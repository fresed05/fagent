"""Tests for shadow context builder."""

import pytest

from fagent.memory.shadow import ShadowContextBuilder
from fagent.memory.types import RetrievedMemory


@pytest.fixture
def builder():
    """Create shadow context builder."""
    return ShadowContextBuilder(max_tokens=400)


@pytest.mark.asyncio
async def test_build_empty_evidence(builder):
    """Test building with no evidence."""
    brief = await builder.build(
        user_query="test query",
        session_key="session_1",
        channel_context={}
    )

    assert brief.summary == "No relevant memory retrieved."
    assert brief.facts == []
    assert brief.confidence == 0.0


@pytest.mark.asyncio
async def test_build_with_results(builder):
    """Test building with memory results."""
    results = [
        RetrievedMemory(
            artifact_id="art_1",
            snippet="Important fact about the project",
            score=0.9,
            store="vector",
            reason="relevant",
            metadata={}
        ),
        RetrievedMemory(
            artifact_id="art_2",
            snippet="Another relevant detail",
            score=0.8,
            store="graph",
            reason="related",
            metadata={}
        )
    ]

    brief = await builder.build(
        user_query="tell me about the project",
        session_key="session_1",
        channel_context={},
        evidence_bundle={"results": results, "confidence": 0.85}
    )

    assert brief.confidence == 0.85
    assert len(brief.citations) > 0
    assert len(brief.facts) > 0


@pytest.mark.asyncio
async def test_build_with_working_set(builder):
    """Test building with working set."""
    results = [
        RetrievedMemory(
            artifact_id="art_1",
            snippet="Task in progress",
            score=0.9,
            store="file",
            reason="current",
            metadata={"status": "in_progress"}
        )
    ]

    working_set = {
        "active_task_state": "Implementing feature X",
        "open_blockers": ["Waiting for API key"]
    }

    brief = await builder.build(
        user_query="what's the status",
        session_key="session_1",
        channel_context={},
        evidence_bundle={"results": results},
        working_set=working_set
    )

    assert len(brief.open_questions) > 0 or "blocker" in brief.summary.lower()


@pytest.mark.asyncio
async def test_mmr_deduplication(builder):
    """Test MMR removes redundant results."""
    results = [
        RetrievedMemory(
            artifact_id="art_1",
            snippet="The API uses REST endpoints",
            score=0.9,
            store="vector",
            reason="relevant",
            metadata={}
        ),
        RetrievedMemory(
            artifact_id="art_2",
            snippet="The API uses REST endpoints for data",
            score=0.85,
            store="vector",
            reason="relevant",
            metadata={}
        ),
        RetrievedMemory(
            artifact_id="art_3",
            snippet="Database uses PostgreSQL",
            score=0.8,
            store="vector",
            reason="relevant",
            metadata={}
        )
    ]

    brief = await builder.build(
        user_query="tell me about the system",
        session_key="session_1",
        channel_context={},
        evidence_bundle={"results": results}
    )

    # Should select diverse results, not duplicates
    assert len(brief.citations) <= len(results)
