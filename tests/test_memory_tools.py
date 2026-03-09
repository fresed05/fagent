import json
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
    episode = EpisodeRecord(
        episode_id="ep-entity",
        session_key="cli:direct",
        turn_id="turn-000003",
        channel="cli",
        chat_id="direct",
        user_text="we use lancedb for vector memory",
        assistant_text="lancedb is linked to memory graph",
        timestamp="2026-03-09T16:20:00",
    )
    await orchestrator.ingest_episode(episode)

    tool = MemoryGetEntityTool(orchestrator)
    payload = json.loads(await tool.execute("lancedb"))

    assert payload["status"] == "ok"
    assert payload["entity"]["label"]


@pytest.mark.asyncio
async def test_workflow_tool_runs_steps_and_records_llm_help() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    workflow = WorkflowTool(registry, provider=StubProvider(), model="stub")

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
    workflow = WorkflowTool(registry, provider=StubProvider(), model="stub")

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
    workflow = WorkflowTool(registry, provider=StubProvider(), model="stub")

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
    workflow = WorkflowTool(registry, provider=StubProvider(), model="stub")

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
    workflow = WorkflowTool(registry, provider=StubProvider(), model="stub")

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
