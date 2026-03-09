from pathlib import Path

import pytest

from fagent.config.schema import MemoryConfig
from fagent.memory.orchestrator import MemoryOrchestrator
from fagent.memory.types import EpisodeRecord


@pytest.mark.asyncio
async def test_embedding_cache_reuses_vector_for_unchanged_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = MemoryConfig()
    config.vector.embedding_model = "text-embedding-3-small"
    config.vector.embedding_api_base = "https://embeddings.example/v1"
    config.vector.embedding_api_key = "test-key"
    config.vector.cache_ttl_s = 3600

    call_count = {"count": 0}

    class _Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            call_count["count"] += 1
            return {
                "data": [
                    {"embedding": [1.0, 0.0, 0.0]}
                    for _ in self.payload["input"]
                ]
            }

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            return _Response(json)

    monkeypatch.setattr("fagent.memory.vector.httpx.Client", _Client)

    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, config=config, model="test-model")
    episode = EpisodeRecord(
        episode_id="ep-cache",
        session_key="cli:direct",
        turn_id="turn-000001",
        channel="cli",
        chat_id="direct",
        user_text="remember this stable fact",
        assistant_text="stable fact saved",
        timestamp="2026-03-09T17:00:00",
    )

    await orchestrator.ingest_episode(episode)
    await orchestrator.rebuild_vectors()

    assert call_count["count"] >= 1
    assert call_count["count"] < 5
    cached = orchestrator.registry.get_embedding_cache(
        "ep-cache",
        orchestrator.vector_backend._content_hash(episode.content),
        orchestrator.vector_backend.embedding_client.embedding_version,
    )
    assert cached is not None
