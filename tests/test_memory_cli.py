from typer.testing import CliRunner

from fagent.cli.commands import app
from fagent.memory.orchestrator import MemoryOrchestrator
from fagent.memory.types import RetrievedMemory

runner = CliRunner()


def test_memory_help_lists_commands() -> None:
    result = runner.invoke(app, ["memory", "--help"])

    assert result.exit_code == 0
    assert "doctor" in result.stdout
    assert "backfill" in result.stdout
    assert "rebuild-vectors" in result.stdout
    assert "query-v2" in result.stdout
    assert "inspect-session" in result.stdout
    assert "inspect-task-graph" in result.stdout
    assert "inspect-experience" in result.stdout
    assert "inspect-graph-jobs" in result.stdout
    assert "graph-ui" in result.stdout


def test_memory_query_v2_command_renders_results(monkeypatch, tmp_path) -> None:
    class _Registry:
        def latest_session_rollup(self, _session_key):
            return None

        def latest_workflow_snapshots(self, _session_key, limit=5):
            return []

        def list_task_nodes(self, _session_key, limit=12):
            return []

        def get_task_edges_for_node(self, _task_id, _node_id, limit=16):
            return []

        def list_artifacts(self, limit=10000):
            return []

        def search_task_nodes(self, _query, limit=1000):
            return []

        def list_experience_patterns(self, session_key=None, limit=32):
            return []

    class _StubMemory(MemoryOrchestrator):
        def __init__(self):
            self.registry = _Registry()

        async def search_v2(self, *args, **kwargs):
            return {
                "intent": "workflow_recall",
                "retrieval_strategy": "balanced",
                "confidence": 0.91,
                "used_stores": ["task_graph", "experience"],
                "raw_escalated": False,
                "results": [
                    RetrievedMemory(
                        artifact_id="workflow:abc",
                        store="workflow",
                        score=0.91,
                        snippet="Embedding failed because of model mismatch",
                        reason="Recent workflow snapshot",
                        metadata={},
                    )
                ],
            }

    monkeypatch.setattr("fagent.cli.commands._build_memory_orchestrator", lambda config, workspace: (None, _StubMemory()))
    result = runner.invoke(app, ["memory", "query-v2", "embedding workflow", "--session", "cli:direct"])

    assert result.exit_code == 0
    assert "workflow_recall" in result.stdout
    assert "workflow:abc" in result.stdout


def test_memory_inspect_experience_command_renders_patterns(monkeypatch) -> None:
    class _Pattern:
        pattern_key = "pat1"
        category = "provider_constraint"
        evidence_count = 2
        trigger = "endpoint rejected model"
        recovery = "switch model"

    class _Registry:
        def list_experience_patterns(self, session_key=None, limit=32):
            return [_Pattern()]

    class _StubMemory:
        def __init__(self):
            self.registry = _Registry()

    monkeypatch.setattr("fagent.cli.commands._build_memory_orchestrator", lambda config, workspace: (None, _StubMemory()))
    result = runner.invoke(app, ["memory", "inspect-experience"])

    assert result.exit_code == 0
    assert "Experience Patterns" in result.stdout
    assert "pat1" in result.stdout
    assert "switch model" in result.stdout


def test_memory_graph_ui_command_prints_url(monkeypatch, tmp_path) -> None:
    class _StubMemory:
        registry = object()

    class _Manager:
        def start(self, orchestrator, *, port=0, query=None, session_key=None, open_browser=True):
            assert orchestrator is not None
            assert query == "neo4j"
            assert session_key == "cli:direct"
            assert open_browser is False
            return "http://127.0.0.1:9999/?query=neo4j&session=cli%3Adirect"

        def wait_forever(self):
            return None

    monkeypatch.setattr(
        "fagent.cli.commands._build_memory_orchestrator",
        lambda config, workspace: (type("Cfg", (), {"workspace_path": tmp_path})(), _StubMemory()),
    )
    monkeypatch.setattr("fagent.cli.commands._get_graph_ui_manager", lambda _workspace: _Manager())

    result = runner.invoke(
        app,
        ["memory", "graph-ui", "--query", "neo4j", "--session", "cli:direct", "--no-open"],
    )

    assert result.exit_code == 0
    assert "Graph UI" in result.stdout
    assert "127.0.0.1:9999" in result.stdout


def test_memory_inspect_graph_jobs_renders_rows(monkeypatch) -> None:
    class _Registry:
        def list_graph_jobs(self, limit=12):
            return [{
                "episode_id": "ep-1",
                "status": "retry",
                "attempts": 2,
                "updated_at": "2026-03-10T10:00:00",
                "error": "graph_extract_unavailable",
            }]

    class _StubMemory:
        def __init__(self):
            self.registry = _Registry()

    monkeypatch.setattr("fagent.cli.commands._build_memory_orchestrator", lambda config, workspace: (None, _StubMemory()))
    result = runner.invoke(app, ["memory", "inspect-graph-jobs"])

    assert result.exit_code == 0
    assert "Graph Jobs" in result.stdout
    assert "ep-1" in result.stdout
    assert "graph_extract_unavaila" in result.stdout
