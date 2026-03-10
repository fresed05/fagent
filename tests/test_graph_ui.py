import json
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from fagent.agent.loop import AgentLoop
from fagent.bus.queue import MessageBus
from fagent.memory.graph_ui import get_graph_ui_manager
from fagent.memory.orchestrator import MemoryOrchestrator
from fagent.providers.base import LLMProvider, LLMResponse


class _StubProvider(LLMProvider):
    async def chat(self, *args, **kwargs):
        return LLMResponse(content="ok")

    def get_default_model(self) -> str:
        return "stub"


def _http_json(method: str, url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def test_graph_ui_server_serves_static_and_api(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="stub")
    orchestrator.upsert_graph_node(node_id="node:a", label="Node A", metadata={"kind": "entity"})
    orchestrator.upsert_graph_node(node_id="node:b", label="Node B", metadata={"kind": "fact"})
    orchestrator.upsert_graph_edge(
        source_id="node:a",
        target_id="node:b",
        relation="relates_to",
        weight=1.0,
        metadata={"source": "test"},
    )

    manager = get_graph_ui_manager(tmp_path)
    url = manager.start(orchestrator, open_browser=False)

    try:
        with urlopen(url, timeout=5) as response:  # noqa: S310
            body = response.read().decode("utf-8")
        with urlopen(f"{url}assets/styles.css", timeout=5) as response:  # noqa: S310
            css = response.read().decode("utf-8")
        payload = _http_json("GET", f"{url}api/graph?query=node")
        node_payload = _http_json("GET", f"{url}api/graph/node/node%3Aa")
        layout_payload = _http_json(
            "POST",
            f"{url}api/graph/layouts",
            {"items": [{"node_id": "node:a", "x": 12, "y": 24, "pinned": False}]},
        )

        assert "fagent graph" in body
        assert ".masthead" in css
        assert any(item["id"] == "node:a" for item in payload["nodes"])
        assert node_payload["id"] == "node:a"
        assert layout_payload["saved"] == 1
    finally:
        manager.stop()


def test_graph_ui_api_requires_scope_for_default_snapshot(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="stub")
    orchestrator.upsert_graph_node(node_id="entity:test", label="Test", metadata={"kind": "entity"})
    manager = get_graph_ui_manager(tmp_path)
    url = manager.start(orchestrator, open_browser=False)

    try:
        payload = _http_json("GET", f"{url}api/graph")
        assert payload["nodes"] == []
        assert payload["edges"] == []
        assert "session or query" in payload["message"].lower()
    finally:
        manager.stop()


def test_graph_ui_api_supports_crud(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="stub")
    manager = get_graph_ui_manager(tmp_path)
    url = manager.start(orchestrator, open_browser=False)

    try:
        node_payload = _http_json(
            "POST",
            f"{url}api/graph/nodes",
            {"id": "node:crud", "label": "CRUD", "metadata_json": "{\"kind\":\"entity\"}"},
        )
        edge_payload = _http_json(
            "POST",
            f"{url}api/graph/edges",
            {
                "source_id": "node:crud",
                "target_id": "node:crud",
                "relation": "loops_to",
                "weight": 2,
                "metadata_json": "{\"source\":\"ui\"}",
            },
        )
        delete_payload = _http_json("DELETE", f"{url}api/graph/edges/node%3Acrud/loops_to/node%3Acrud")
        delete_node_payload = _http_json("DELETE", f"{url}api/graph/nodes/node%3Acrud")

        assert node_payload["node"]["id"] == "node:crud"
        assert edge_payload["edge"]["relation"] == "loops_to"
        assert delete_payload["deleted"] is True
        assert delete_node_payload["deleted"] is True
    finally:
        manager.stop()


def test_graph_ui_clustered_mode_collapses_dense_hub_neighbors(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="stub")
    orchestrator.upsert_graph_node(node_id="hub:root", label="Hub", metadata={"kind": "entity"})
    for index in range(8):
        node_id = f"fact:{index}"
        orchestrator.upsert_graph_node(node_id=node_id, label=f"Fact {index}", metadata={"kind": "fact"})
        orchestrator.upsert_graph_edge(
            source_id="hub:root",
            target_id=node_id,
            relation="supports",
            weight=1.0,
            metadata={"source": "test"},
        )

    payload = orchestrator.export_graph_subgraph(query=":", mode="global-clustered")

    assert payload["mode"] == "global-clustered"
    assert payload["hidden_node_count"] >= 5
    assert payload["clusters"]
    assert any(node["metadata"].get("is_cluster") for node in payload["nodes"])


def test_graph_ui_raw_mode_falls_back_to_clustered_when_graph_is_too_large(tmp_path: Path) -> None:
    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="stub")
    orchestrator.upsert_graph_node(node_id="hub:root", label="Hub", metadata={"kind": "entity"})
    for index in range(95):
        node_id = f"leaf:{index}"
        orchestrator.upsert_graph_node(node_id=node_id, label=f"Leaf {index}", metadata={"kind": "fact"})
        orchestrator.upsert_graph_edge(
            source_id="hub:root",
            target_id=node_id,
            relation="supports",
            weight=1.0,
            metadata={"source": "test"},
        )

    payload = orchestrator.export_graph_subgraph(query=":", mode="global-raw", node_limit=200, edge_limit=400)

    assert payload["requested_mode"] == "global-raw"
    assert payload["mode"] == "global-clustered"
    assert "Switched to clustered mode" in payload["message"]


@pytest.mark.asyncio
async def test_graph_slash_command_returns_url(monkeypatch, tmp_path: Path) -> None:
    class _Manager:
        def start(self, orchestrator, *, port=0, query=None, session_key=None, open_browser=True):
            assert query == "neo4j"
            assert session_key == "cli:direct"
            assert open_browser is True
            return "http://127.0.0.1:7777/?query=neo4j"

    monkeypatch.setattr("fagent.agent.loop.get_graph_ui_manager", lambda _workspace: _Manager())

    loop = AgentLoop(
        bus=MessageBus(),
        provider=_StubProvider(),
        workspace=tmp_path,
        model="stub",
    )

    response = await loop.process_direct("/graph neo4j")

    assert response == "Graph UI: http://127.0.0.1:7777/?query=neo4j"
