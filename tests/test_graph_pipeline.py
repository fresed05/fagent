from pathlib import Path

import pytest

from fagent.memory.orchestrator import MemoryOrchestrator
from fagent.memory.types import EpisodeRecord
from fagent.providers.base import LLMResponse, ToolCallRequest


@pytest.mark.asyncio
async def test_graph_pipeline_skips_without_llm(tmp_path: Path) -> None:
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
    assert job.status == "skipped"
    assert job.error == "graph_extract_unavailable"
    assert results == []


class _ToolGraphProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(id="1", name="search_graph", arguments={"query": "lancedb", "limit": 3}),
                    ToolCallRequest(
                        id="2",
                        name="create_entity",
                        arguments={"entity_id": "entity:lancedb", "label": "LanceDB", "kind": "technology", "confidence": 0.92},
                    ),
                    ToolCallRequest(
                        id="3",
                        name="create_entity",
                        arguments={"entity_id": "entity:shadow-context", "label": "Shadow Context", "kind": "workflow", "confidence": 0.9},
                    ),
                    ToolCallRequest(
                        id="4",
                        name="create_relation",
                        arguments={
                            "source_id": "entity:lancedb",
                            "target_id": "entity:shadow-context",
                            "relation": "supports",
                            "confidence": 0.88,
                        },
                    ),
                    ToolCallRequest(
                        id="5",
                        name="create_fact",
                        arguments={
                            "fact_id": "fact:lancedb-shadow",
                            "statement": "Graph memory should relate LanceDB to shadow context.",
                            "subject_id": "entity:lancedb",
                            "confidence": 0.86,
                        },
                    ),
                ],
            )
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="6",
                    name="finish_graph_plan",
                    arguments={"reason": "Durable technical decision captured."},
                )
            ],
        )

    def get_default_model(self) -> str:
        return "stub"


@pytest.mark.asyncio
async def test_graph_pipeline_creates_job_and_edges_with_tool_agent(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=_ToolGraphProvider(), model="test-model")
    orchestrator.graph_backend.extract_model = "stub-graph"
    episode = EpisodeRecord(
        episode_id="ep-graph-2",
        session_key="cli:direct",
        turn_id="turn-000011",
        channel="cli",
        chat_id="direct",
        user_text="we decided to use lancedb and shadow context",
        assistant_text="graph memory should relate lancedb to shadow context",
        timestamp="2026-03-09T18:02:00",
    )

    await orchestrator.ingest_episode(episode)

    job = orchestrator.registry.get_graph_job("ep-graph-2")
    results = orchestrator.search("lancedb", stores=["graph"], top_k=5)

    assert job is not None
    assert job.status == "done"
    assert any("LanceDB" in item.snippet for item in results)
    assert orchestrator.registry.get_graph_node("entity:lancedb") is not None
    assert orchestrator.registry.get_graph_edge("entity:lancedb", "entity:shadow-context", "supports") is not None
