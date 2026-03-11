import json
import sqlite3
from pathlib import Path

import pytest

from fagent.agent.tools.memory_search import (
    MemoryGetArtifactTool,
    MemoryGetDailyNoteTool,
    MemoryGetEntityTool,
    MemorySearchTool,
    MemorySearchV2Tool,
)
from fagent.agent.tools.registry import ToolRegistry
from fagent.agent.tools.workflow import WorkflowTool
from fagent.memory.orchestrator import MemoryOrchestrator
from fagent.memory.vector import EmbeddedVectorStore
from fagent.memory.types import EpisodeRecord
from fagent.providers.base import LLMProvider, LLMResponse


class StubProvider(LLMProvider):
    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
    ):
        text = str(messages[-1]["content"])
        if "Repair this workflow step" in text:
            if "strict_echo" in text:
                return LLMResponse(content='{"action":"strict_echo","args":{"text":"repaired"},"needs_llm":false}')
            return LLMResponse(content='{"action":"echo","args":{"text":"repaired"},"needs_llm":false}')
        return LLMResponse(content='{"decision":"retry with a narrower query"}')

    def get_default_model(self) -> str:
        return "stub"


class EchoTool:
    name = "echo"
    description = "Echo text"
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, **kwargs):
        return kwargs["text"]

    def to_schema(self):
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}

    def cast_params(self, params):
        return params

    def validate_params(self, params):
        return []


class StrictEchoTool(EchoTool):
    name = "strict_echo"
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string", "minLength": 1}},
        "required": ["text"],
    }

    async def execute(self, **kwargs):
        if kwargs.get("text") != "repaired":
            return "Error: bad payload"
        return kwargs["text"]


class StubEmbeddingClient:
    def __init__(self, vector: list[float] | None = None) -> None:
        self.vector = vector or [1.0, 0.0]
        self.embedding_version = "stub-embedding"

    def healthcheck(self) -> bool:
        return True

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [list(self.vector) for _ in texts]


@pytest.mark.asyncio
async def test_memory_search_tool_returns_ranked_results(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")
    episode = EpisodeRecord(
        episode_id="ep-memory-search",
        session_key="cli:direct",
        turn_id="turn-000001",
        channel="cli",
        chat_id="direct",
        user_text="we chose shadow context for continuity",
        assistant_text="shadow context will build a compact brief",
        timestamp="2026-03-09T16:00:00",
    )
    await orchestrator.ingest_episode(episode)

    tool = MemorySearchTool(orchestrator)
    payload = json.loads(await tool.execute(query="shadow context", stores=["file", "graph"], top_k=5))

    assert payload["count"] >= 1
    assert any(item["store"] in {"file", "graph"} for item in payload["results"])
    assert "empty_reason_codes" in payload


@pytest.mark.asyncio
async def test_memory_search_v2_surfaces_task_and_experience_memory(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")
    orchestrator.record_workflow_snapshot(
        session_key="cli:direct",
        turn_id="turn-000010",
        step_index=6,
        goal="debug embeddings workflow",
        current_state="Embedding request failed on provider mismatch",
        open_blockers=["provider mismatch on embeddings endpoint"],
        next_step="retry with supported model",
        citations=["turn-000010"],
        tools_used=["run_workflow", "memory_search_v2"],
    )
    orchestrator.record_experience_event(
        category="provider_constraint",
        session_key="cli:direct",
        trigger_text="embeddings endpoint rejected gemini model",
        recovery_text="switch to supported embedding model",
        metadata={"source": "test"},
    )
    orchestrator.record_experience_event(
        category="provider_constraint",
        session_key="cli:direct",
        trigger_text="embeddings endpoint rejected gemini model",
        recovery_text="switch to supported embedding model",
        metadata={"source": "test"},
    )

    tool = MemorySearchV2Tool(orchestrator)
    payload = json.loads(
        await tool.execute(
            query="what failed in the workflow with embeddings",
            session_scope="cli:direct",
            allow_raw_escalation=True,
        )
    )

    assert payload["intent"] == "workflow_recall"
    assert payload["count"] >= 1
    assert any(item["store"] in {"workflow", "task_graph", "experience"} for item in payload["results"])
    assert payload["store_attempts"]


@pytest.mark.asyncio
async def test_memory_get_artifact_and_daily_note_tools(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")
    episode = EpisodeRecord(
        episode_id="ep-artifact",
        session_key="cli:direct",
        turn_id="turn-000002",
        channel="cli",
        chat_id="direct",
        user_text="remember daily note retrieval",
        assistant_text="stored in notes and artifacts",
        timestamp="2026-03-09T16:10:00",
    )
    await orchestrator.ingest_episode(episode)

    artifact_tool = MemoryGetArtifactTool(orchestrator)
    note_tool = MemoryGetDailyNoteTool(orchestrator)

    artifact_payload = json.loads(await artifact_tool.execute("ep-artifact:history"))
    note_payload = json.loads(await note_tool.execute("2026-03-09"))

    assert artifact_payload["status"] == "ok"
    assert artifact_payload["artifact"]["id"] == "ep-artifact:history"
    assert note_payload["status"] == "ok"
    assert "turn-000002" in note_payload["note"]["content"]


@pytest.mark.asyncio
async def test_memory_get_entity_tool_returns_graph_node(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")
    orchestrator.registry.upsert_graph_node(
        "entity:lancedb",
        label="lancedb",
        metadata={
            "kind": "entity",
            "canonical_name": "lancedb",
            "aliases": ["lancedb"],
            "session_key": "cli:direct",
        },
    )

    tool = MemoryGetEntityTool(orchestrator)
    payload = json.loads(await tool.execute("entity:lancedb"))

    assert payload["status"] == "ok"
    assert payload["resolution"] == "graph_entity"
    assert payload["entity"]["label"]
    assert payload["entity"]["match_source"] == "direct_id"


@pytest.mark.asyncio
async def test_memory_get_entity_tool_returns_ranked_graph_match(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")
    orchestrator.registry.upsert_graph_node(
        "entity:lancedb",
        label="lancedb",
        metadata={"kind": "entity", "aliases": ["lance db"], "canonical_name": "lancedb"},
    )
    orchestrator.registry.replace_graph_aliases(
        "entity:lancedb",
        [
            {"alias_text": "lancedb", "alias_language": "en", "is_canonical": 1},
            {"alias_text": "lance db", "alias_language": "en", "is_canonical": 0},
        ],
    )

    tool = MemoryGetEntityTool(orchestrator)
    payload = json.loads(await tool.execute("lance db"))

    assert payload["status"] == "ok"
    assert payload["resolution"] == "graph_entity"
    assert payload["entity"]["match_source"] == "ranked_graph_search"
    assert payload["entity"]["match_confidence"] > 0


@pytest.mark.asyncio
async def test_memory_get_entity_tool_returns_honest_artifact_fallback(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")
    episode = EpisodeRecord(
        episode_id="ep-artifact-fallback",
        session_key="cli:direct",
        turn_id="turn-000004",
        channel="cli",
        chat_id="direct",
        user_text="remember nvidia embedding model selection",
        assistant_text="embedding model remembered for later",
        timestamp="2026-03-09T16:30:00",
    )
    await orchestrator.ingest_episode(episode)

    tool = MemoryGetEntityTool(orchestrator)
    payload = json.loads(await tool.execute("nvidia"))

    assert payload["status"] == "degraded"
    assert payload["resolution"] == "artifact_fallback"
    assert payload["entity"]["metadata"]["resolution"] == "artifact_fallback"


@pytest.mark.asyncio
async def test_memory_get_entity_tool_returns_not_found(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")
    tool = MemoryGetEntityTool(orchestrator)

    payload = json.loads(await tool.execute("totally-unknown-entity"))

    assert payload["status"] == "not_found"


def test_embedded_vector_store_backfills_legacy_scope_columns(tmp_path: Path) -> None:
    store = EmbeddedVectorStore(tmp_path, collection="memory")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DELETE FROM vectors")
        conn.execute(
            """
            INSERT INTO vectors(
                id, content, vector_json, metadata_json, session_key, artifact_type, channel, chat_id, turn_id, search_text,
                content_hash, embedding_version
            )
            VALUES (?, ?, ?, ?, '', '', '', '', '', '', ?, ?)
            """,
            (
                "legacy-row",
                "local SQLite graph memory",
                json.dumps([1.0, 0.0]),
                json.dumps(
                    {
                        "artifact_id": "legacy-row",
                        "session_key": "cli:legacy",
                        "artifact_type": "session_turn",
                        "channel": "cli",
                        "chat_id": "direct",
                        "turn_id": "turn-legacy",
                    }
                ),
                "hash-legacy",
                "stub-embedding",
            ),
        )
    store = EmbeddedVectorStore(tmp_path, collection="memory")
    rows = store.query([1.0, 0.0], top_k=3, filters={"session_key": "cli:legacy", "artifact_type": "session_turn"}, query_text="local SQLite")

    assert rows
    assert rows[0]["session_key"] == "cli:legacy"
    assert rows[0]["artifact_type"] == "session_turn"


@pytest.mark.asyncio
async def test_memory_search_v2_reports_empty_diagnostics_without_session_scope(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")
    episode = EpisodeRecord(
        episode_id="ep-empty-diagnostics",
        session_key="cli:direct",
        turn_id="turn-000005",
        channel="cli",
        chat_id="direct",
        user_text="remember local sqlite graph memory and background extractor",
        assistant_text="stored local sqlite graph memory and background extractor",
        timestamp="2026-03-09T16:40:00",
    )
    await orchestrator.ingest_episode(episode)

    tool = MemorySearchV2Tool(orchestrator)
    payload = json.loads(
        await tool.execute(
            query="telegram placeholder github",
            stores=["file", "graph"],
            allow_raw_escalation=True,
        )
    )

    assert payload["count"] == 0
    assert "no_matching_data" in payload["empty_reason_codes"]
    assert "query_data_mismatch" in payload["empty_reason_codes"]
    assert payload["raw_escalation_reason"] == "raw_escalation_skipped_no_session_scope"
    assert payload["session_scope_applied"] is False


@pytest.mark.asyncio
async def test_memory_search_v2_returns_realistic_fixture_results(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")
    episode = EpisodeRecord(
        episode_id="ep-realistic-memory",
        session_key="cli:live-memory",
        turn_id="turn-000006",
        channel="cli",
        chat_id="direct",
        user_text="Please remember this exact fact for future turns: We selected the external embeddings model nvidia/llama-nemotron-embed-vl-1b-v2 and we use local SQLite graph memory with a background extractor.",
        assistant_text="Got it, I will remember the embeddings model and the local SQLite graph memory setup.",
        timestamp="2026-03-09T16:50:00",
    )
    await orchestrator.ingest_episode(episode)

    tool = MemorySearchV2Tool(orchestrator)
    payload = json.loads(
        await tool.execute(
            query="local SQLite graph memory",
            stores=["file", "graph"],
            session_scope="cli:live-memory",
        )
    )

    assert payload["count"] >= 1
    assert any("local SQLite graph memory" in item["snippet"] for item in payload["results"])


@pytest.mark.asyncio
async def test_workflow_tool_runs_steps_and_records_llm_help() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    workflow = WorkflowTool(registry, workspace=Path.cwd(), provider=StubProvider(), model="stub")

    payload = json.loads(
        await workflow.execute(
            goal="echo once",
            steps=[{"action": "echo", "args": {"text": "ok"}, "needs_llm": True}],
            allowed_tools=["echo"],
            llm_assist_mode="allow",
        )
    )

    assert payload["status"] == "completed"
    assert any("llm_note" in item for item in payload["execution_log"])


@pytest.mark.asyncio
async def test_workflow_tool_normalizes_string_steps() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    workflow = WorkflowTool(registry, workspace=Path.cwd(), provider=StubProvider(), model="stub")

    payload = json.loads(
        await workflow.execute(
            goal="echo once",
            steps=["echo ok"],
            allowed_tools=["echo"],
        )
    )

    assert payload["status"] == "completed"
    assert payload["execution_log"][0]["args"]["text"] == "ok"


@pytest.mark.asyncio
async def test_workflow_tool_normalizes_embedded_action_text() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    workflow = WorkflowTool(registry, workspace=Path.cwd(), provider=StubProvider(), model="stub")

    payload = json.loads(
        await workflow.execute(
            goal="echo once",
            steps=[{"action": "echo text=\"hello world\""}],
            allowed_tools=["echo"],
        )
    )

    assert payload["status"] == "completed"
    assert payload["execution_log"][0]["args"]["text"] == "hello world"


@pytest.mark.asyncio
async def test_workflow_tool_repairs_blocked_step_with_light_llm() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    workflow = WorkflowTool(registry, workspace=Path.cwd(), provider=StubProvider(), model="stub")

    payload = json.loads(
        await workflow.execute(
            goal="repair blocked step",
            steps=[{"action": "broken_tool", "args": {"text": "x"}}],
            allowed_tools=["echo"],
            llm_assist_mode="on_error",
        )
    )

    assert payload["status"] == "completed"
    assert any(item.get("repair_applied", {}).get("action") == "echo" for item in payload["execution_log"])


@pytest.mark.asyncio
async def test_workflow_tool_repairs_failed_execution_and_retries() -> None:
    registry = ToolRegistry()
    registry.register(StrictEchoTool())
    workflow = WorkflowTool(registry, workspace=Path.cwd(), provider=StubProvider(), model="stub")

    payload = json.loads(
        await workflow.execute(
            goal="repair failed step",
            steps=[{"action": "strict_echo", "args": {"text": "wrong"}}],
            allowed_tools=["strict_echo"],
            llm_assist_mode="on_error",
        )
    )

    assert payload["status"] == "completed"
    assert any(item.get("repair_retry", {}).get("args", {}).get("text") == "repaired" for item in payload["execution_log"])


@pytest.mark.asyncio
async def test_auto_summary_archives_old_history(tmp_path: Path) -> None:
    from fagent.session.manager import Session

    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")
    orchestrator.config.auto_summarize.max_context_tokens = 20
    orchestrator.config.auto_summarize.min_new_messages = 2
    session = Session(key="cli:direct")
    session.metadata["estimated_context_tokens"] = 100
    session.messages = [
        {"role": "user", "content": "first request", "turn_id": "turn-000001"},
        {"role": "assistant", "content": "first reply", "turn_id": "turn-000001"},
        {"role": "user", "content": "second request", "turn_id": "turn-000002"},
        {"role": "assistant", "content": "second reply", "turn_id": "turn-000002"},
        {"role": "user", "content": "latest request", "turn_id": "turn-000003"},
        {"role": "assistant", "content": "latest reply", "turn_id": "turn-000003"},
    ]

    artifact = await orchestrator.maybe_auto_summarize_session(session)

    assert artifact is not None
    assert artifact.type == "session_summary"
    assert session.metadata["summary_cutoff_idx"] >= 1
