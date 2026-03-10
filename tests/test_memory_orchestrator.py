from pathlib import Path

import pytest

from fagent.config.schema import MemoryConfig
from fagent.memory.file_store import FileMemoryStore
from fagent.memory.orchestrator import MemoryOrchestrator
from fagent.memory.types import EpisodeRecord
from fagent.providers.base import LLMResponse, ToolCallRequest
from fagent.session.manager import Session


@pytest.mark.asyncio
async def test_memory_orchestrator_ingests_episode_and_is_idempotent(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")
    episode = EpisodeRecord(
        episode_id="ep-1",
        session_key="cli:direct",
        turn_id="turn-000001",
        channel="cli",
        chat_id="direct",
        user_text="Мы выбрали стек памяти на базе qdrant и neo4j.",
        assistant_text="Зафиксировал default stack: qdrant для vector, neo4j для graph.",
        timestamp="2026-03-09T12:00:00",
    )

    await orchestrator.ingest_episode(episode)
    await orchestrator.ingest_episode(episode)

    history = (tmp_path / "memory" / "HISTORY.md").read_text(encoding="utf-8")
    daily = (tmp_path / "memory" / "daily" / "2026-03-09.md").read_text(encoding="utf-8")
    memory = (tmp_path / "memory" / "MEMORY.md").read_text(encoding="utf-8")

    assert "qdrant" in history.lower()
    assert "turn-000001" in daily
    assert "default stack" in memory.lower()
    assert orchestrator.registry.get_job_status("ep-1") == "done"


@pytest.mark.asyncio
async def test_memory_orchestrator_builds_shadow_context_from_file_memory(tmp_path: Path) -> None:
    store = FileMemoryStore(tmp_path)
    episode = EpisodeRecord(
        episode_id="ep-2",
        session_key="cli:direct",
        turn_id="turn-000002",
        channel="cli",
        chat_id="direct",
        user_text="Мы решили добавить shadow context.",
        assistant_text="Shadow context будет собирать краткий brief из memory backends.",
        timestamp="2026-03-09T13:00:00",
    )
    store.ingest_episode(episode)
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")

    brief = await orchestrator.prepare_shadow_context(
        "shadow context",
        "cli:direct",
        {"channel": "cli", "chat_id": "direct"},
    )

    assert brief is not None
    assert "shadow context" in brief.summary.lower()
    assert brief.citations


@pytest.mark.asyncio
async def test_memory_backfill_uses_turn_ids(tmp_path: Path) -> None:
    session = Session(key="cli:direct")
    session.metadata["turn_seq"] = 1
    session.messages = [
        {"role": "user", "content": "Нужна память", "turn_id": "turn-000001", "timestamp": "2026-03-09T12:00:00"},
        {"role": "assistant", "content": "Сделаем память", "turn_id": "turn-000001", "timestamp": "2026-03-09T12:00:01"},
    ]
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")

    count = await orchestrator.backfill_sessions([session])

    assert count == 1
    artifacts = orchestrator.registry.list_artifacts("session_turn")
    assert len(artifacts) == 1
    assert orchestrator.query("память")


@pytest.mark.asyncio
async def test_vector_memory_uses_external_embeddings_without_local_servers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = MemoryConfig()
    config.vector.embedding_model = "text-embedding-3-small"
    config.vector.embedding_api_base = "https://embeddings.example/v1"
    config.vector.embedding_api_key = "test-key"
    config.graph.backend = "local"

    calls: list[list[str]] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            texts = calls[-1]
            data = []
            for text in texts:
                if "vector recall" in text:
                    data.append({"embedding": [0.0, 1.0, 0.0]})
                else:
                    data.append({"embedding": [1.0, 0.0, 0.0]})
            return {"data": data}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            calls.append(list(json["input"]))
            return _Response()

    monkeypatch.setattr("fagent.memory.vector.httpx.Client", _Client)

    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, config=config, model="test-model")
    episode = EpisodeRecord(
        episode_id="ep-3",
        session_key="cli:direct",
        turn_id="turn-000003",
        channel="cli",
        chat_id="direct",
        user_text="please remember vector recall",
        assistant_text="saved with external embeddings",
        timestamp="2026-03-09T14:00:00",
    )

    await orchestrator.ingest_episode(episode)
    results = orchestrator.query("vector recall")

    assert orchestrator.doctor()["vector"] is True
    assert any("[vector]" in item for item in results)
    assert calls


@pytest.mark.asyncio
async def test_vector_failure_does_not_break_file_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = MemoryConfig()
    config.vector.embedding_model = "text-embedding-3-small"
    config.vector.embedding_api_base = "https://embeddings.example/v1"
    config.vector.embedding_api_key = "test-key"

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            raise RuntimeError("embedding endpoint down")

    monkeypatch.setattr("fagent.memory.vector.httpx.Client", _Client)

    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, config=config, model="test-model")
    episode = EpisodeRecord(
        episode_id="ep-4",
        session_key="cli:direct",
        turn_id="turn-000004",
        channel="cli",
        chat_id="direct",
        user_text="please remember fallback behavior",
        assistant_text="file memory should still work",
        timestamp="2026-03-09T15:00:00",
    )

    await orchestrator.ingest_episode(episode)

    assert (tmp_path / "memory" / "HISTORY.md").exists()
    assert orchestrator.registry.get_job_status("ep-4") == "retry"
    assert any("[file]" in item for item in orchestrator.query("fallback behavior"))


def test_export_graph_subgraph_returns_latest_graph_without_filters(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")
    orchestrator.registry.upsert_graph_node("entity:ssh", "SSH", {"kind": "entity"})
    orchestrator.registry.replace_graph_aliases(
        "entity:ssh",
        [
            {"alias_text": "SSH", "alias_language": "en", "is_canonical": True},
            {"alias_text": "ссш", "alias_language": "ru", "is_canonical": False},
        ],
    )
    orchestrator.registry.upsert_graph_node("fact:ssh-port", "SSH listens on 22/tcp", {"kind": "fact"})
    orchestrator.registry.upsert_graph_edge("entity:ssh", "fact:ssh-port", "described_by", 1.0, {})

    payload = orchestrator.export_graph_subgraph()

    assert len(payload["nodes"]) == 2
    assert len(payload["edges"]) == 1
    assert payload["message"] == "Loaded latest graph snapshot."


def test_get_entity_and_query_resolve_russian_alias_to_english_canonical_node(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")
    orchestrator.registry.upsert_graph_node(
        "entity:shadow-context",
        "shadow context",
        {
            "kind": "workflow",
            "canonical_name": "shadow context",
            "aliases": ["shadow context", "теневой контекст"],
        },
    )
    orchestrator.registry.replace_graph_aliases(
        "entity:shadow-context",
        [
            {"alias_text": "shadow context", "alias_language": "en", "is_canonical": True},
            {"alias_text": "теневой контекст", "alias_language": "ru", "is_canonical": False},
        ],
    )

    entity = orchestrator.get_entity("теневой контекст")
    results = orchestrator.search("теневой контекст", stores=["graph"], top_k=5)

    assert entity is not None
    assert entity["id"] == "entity:shadow-context"
    assert entity["label"] == "shadow context"
    assert any(item.artifact_id == "entity:shadow-context" for item in results)


@pytest.mark.asyncio
async def test_graph_stage_skips_repeated_turns_in_same_session(tmp_path: Path) -> None:
    class _GraphProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def chat(self, *args, **kwargs):
            self.calls += 1
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(id="1", name="create_entity", arguments={"entity_id": "entity:ssh", "label": "SSH", "kind": "entity"}),
                    ToolCallRequest(id="2", name="finish_graph_plan", arguments={"reason": "done"}),
                ],
            )

        def get_default_model(self) -> str:
            return "stub"

    provider = _GraphProvider()
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=provider, model="test-model")
    orchestrator.graph_backend.extract_model = "stub-graph"
    first = EpisodeRecord(
        episode_id="ep-r1",
        session_key="cli:direct",
        turn_id="turn-000101",
        channel="cli",
        chat_id="direct",
        user_text="повтори снова",
        assistant_text="22 — SSH, 3389 — XRDP, 8000 — cliproxyapi.",
        timestamp="2026-03-10T06:00:00",
    )
    second = EpisodeRecord(
        episode_id="ep-r2",
        session_key="cli:direct",
        turn_id="turn-000102",
        channel="cli",
        chat_id="direct",
        user_text="повтори в одну строку",
        assistant_text="22 — SSH, 3389 — XRDP, 8000 — cliproxyapi",
        timestamp="2026-03-10T06:01:00",
    )

    orchestrator._ensure_session_artifact(first)
    status_first = await orchestrator._run_graph_stage(first)
    orchestrator._ensure_session_artifact(second)
    status_second = await orchestrator._run_graph_stage(second)

    assert status_first == "done"
    assert status_second == "skipped"
    assert provider.calls == 1
