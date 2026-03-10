from pathlib import Path

import pytest

from fagent.agent.loop import AgentLoop
from fagent.bus.queue import MessageBus
from fagent.providers.base import LLMResponse


class _StubProvider:
    async def chat(self, *args, **kwargs):
        return LLMResponse(content="Final answer")

    def get_default_model(self) -> str:
        return "stub-model"


@pytest.mark.asyncio
async def test_process_direct_waits_for_post_turn_pipeline(tmp_path: Path) -> None:
    loop = AgentLoop(
        bus=MessageBus(),
        provider=_StubProvider(),
        workspace=tmp_path,
        model="stub-model",
    )

    pipeline_done = {"value": False}

    async def _search_v2(*args, **kwargs):
        return {
            "used_stores": ["file"],
            "count": 0,
            "confidence": 0.0,
            "results": [],
        }

    async def _run_post_turn_pipeline(*args, **kwargs):
        pipeline_done["value"] = True
        return {
            "file_memory": {"status": "ok", "artifacts": 1},
            "graph": {"status": "skipped"},
            "vector": {"status": "skipped", "artifacts": 0},
            "summary": {"status": "not_triggered", "artifact_id": None},
        }

    loop.memory.search_v2 = _search_v2  # type: ignore[method-assign]
    loop.memory.run_post_turn_pipeline = _run_post_turn_pipeline  # type: ignore[method-assign]

    response = await loop.process_direct("hello", on_progress=None)

    assert response == "Final answer"
    assert pipeline_done["value"] is True


@pytest.mark.asyncio
async def test_process_direct_emits_presearch_and_turn_complete(tmp_path: Path) -> None:
    loop = AgentLoop(
        bus=MessageBus(),
        provider=_StubProvider(),
        workspace=tmp_path,
        model="stub-model",
    )

    async def _search_v2(*args, **kwargs):
        return {
            "used_stores": ["file", "graph"],
            "count": 2,
            "confidence": 0.4,
            "results": [],
        }

    async def _run_post_turn_pipeline(*args, **kwargs):
        return {
            "file_memory": {"status": "ok", "artifacts": 1},
            "graph": {"status": "done"},
            "vector": {"status": "ok", "artifacts": 2},
            "summary": {"status": "not_triggered", "artifact_id": None},
        }

    loop.memory.search_v2 = _search_v2  # type: ignore[method-assign]
    loop.memory.run_post_turn_pipeline = _run_post_turn_pipeline  # type: ignore[method-assign]
    events: list[tuple[str, str]] = []

    async def _progress(content: str, **kwargs):
        events.append((str(kwargs.get("stage", "")), str(kwargs.get("status", ""))))

    await loop.process_direct("hello", on_progress=_progress)

    assert ("Pre-search", "ok") in events
    assert ("Turn complete", "done") in events


def test_update_session_usage_prefers_real_prompt_tokens() -> None:
    from fagent.session.manager import Session

    loop = AgentLoop.__new__(AgentLoop)
    session = Session(key="cli:direct")

    loop._update_session_usage(
        session,
        {
            "prompt_tokens": 1400,
            "completion_tokens": 200,
            "total_tokens": 1600,
            "last_prompt_tokens": 900,
            "max_prompt_tokens": 1100,
            "usage_seen": 1,
        },
    )

    assert session.metadata["estimated_context_tokens"] == 900
    assert session.metadata["last_prompt_tokens"] == 900
    assert session.metadata["max_prompt_tokens_in_turn"] == 1100
