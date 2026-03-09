from pathlib import Path

import pytest

from fagent.memory.orchestrator import MemoryOrchestrator
from fagent.memory.types import EpisodeRecord


@pytest.mark.asyncio
async def test_graph_pipeline_creates_job_and_edges(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")
    episode = EpisodeRecord(
        episode_id="ep-graph",
        session_key="cli:direct",
        turn_id="turn-000010",
        channel="cli",
        chat_id="direct",
        user_text="we decided to use lancedb and shadow context",
        assistant_text="graph memory should relate lancedb to shadow context",
        timestamp="2026-03-09T18:00:00",
    )

    await orchestrator.ingest_episode(episode)

    job = orchestrator.registry.get_graph_job("ep-graph")
    results = orchestrator.search("lancedb", stores=["graph"], top_k=5)

    assert job is not None
    assert job.status in {"done", "retry"}
    assert results
