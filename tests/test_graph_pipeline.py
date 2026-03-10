from pathlib import Path

import pytest

from fagent.config.schema import Config
from fagent.memory.graph import LocalGraphBackend
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
        self.last_tool_choice = None

    async def chat(self, *args, **kwargs):
        self.calls += 1
        self.last_tool_choice = kwargs.get("tool_choice")
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


class _ProviderFactoryStub:
    def __init__(self, mapping, fallback=None) -> None:
        self.mapping = mapping
        self.fallback = fallback

    def build_from_profile(self, profile):
        return self.mapping.get(profile.model, self.fallback)


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
    assert orchestrator.provider.last_tool_choice == "required"
    assert any("LanceDB" in item.snippet for item in results)
    assert orchestrator.registry.get_graph_node("entity:lancedb") is not None
    assert orchestrator.registry.get_graph_edge("entity:lancedb", "entity:shadow-context", "supports") is not None


@pytest.mark.asyncio
async def test_graph_pipeline_uses_graph_extract_role_provider(tmp_path: Path) -> None:
    main_provider = _ToolGraphProvider()
    graph_provider = _ToolGraphProvider()
    app_config = Config.model_validate(
        {
            "providers": {
                "main_provider": {"providerKind": "custom", "apiKey": "main-key", "apiBase": "http://main.example/v1"},
                "graph_provider": {"providerKind": "custom", "apiKey": "graph-key", "apiBase": "http://graph.example/v1"},
            },
            "models": {
                "profiles": {
                    "graph_extract": {
                        "provider": "graph_provider",
                        "providerKind": "custom",
                        "model": "graph-model",
                    }
                },
                "roles": {"graph_extract": "graph_extract"},
            },
        }
    )
    orchestrator = MemoryOrchestrator(
        workspace=tmp_path,
        provider=main_provider,
        model="main-model",
        app_config=app_config,
        provider_factory=_ProviderFactoryStub({"graph-model": graph_provider}, fallback=main_provider),
    )
    episode = EpisodeRecord(
        episode_id="ep-graph-3",
        session_key="cli:direct",
        turn_id="turn-000012",
        channel="cli",
        chat_id="direct",
        user_text="we decided to use graph specific provider",
        assistant_text="graph memory should use the graph provider",
        timestamp="2026-03-10T05:12:00",
    )

    await orchestrator.ingest_episode(episode)

    assert orchestrator.graph_backend.provider is graph_provider
    assert graph_provider.calls > 0
    assert main_provider.calls == 0


def test_graph_tool_normalizes_russian_entity_and_relation_to_english(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")
    backend = LocalGraphBackend(tmp_path, orchestrator.registry)
    stage = {"summary": "", "reason": "", "entities": {}, "facts": {}, "relations": []}

    entity_result, finished = backend._run_graph_tool(
        "create_entity",
        {
            "surface_label": "теневой контекст",
            "canonical_english_label": "shadow context",
            "kind": "workflow",
            "aliases": ["теневой контекст", "shadow context"],
        },
        stage,
    )
    relation_result, relation_finished = backend._run_graph_tool(
        "create_relation",
        {
            "source_id": "entity:a",
            "target_id": "entity:b",
            "relation": "использует",
        },
        stage,
    )

    assert entity_result["ok"] is True
    assert finished is False
    assert relation_result["ok"] is True
    assert relation_finished is False
    entity = next(iter(stage["entities"].values()))
    assert entity["name"] == "shadow context"
    assert entity["source_language"] == "ru"
    assert stage["relations"][0]["type"] == "uses"


def test_graph_tool_skips_low_confidence_non_english_entity(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")
    backend = LocalGraphBackend(tmp_path, orchestrator.registry)
    stage = {"summary": "", "reason": "", "entities": {}, "facts": {}, "relations": []}

    result, _ = backend._run_graph_tool(
        "create_entity",
        {
            "surface_label": "непонятная сущность",
            "kind": "concept",
        },
        stage,
    )

    assert result["ok"] is False
    assert result["error"] == "english_canonicalization_required"
    assert stage["entities"] == {}
