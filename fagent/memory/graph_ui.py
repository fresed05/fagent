"""Local graph UI HTTP server and per-workspace server manager."""

from __future__ import annotations

import json
import threading
import webbrowser
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from fagent.memory.orchestrator import MemoryOrchestrator


_STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "graph_ui"
_MANAGERS: dict[str, "GraphUiServerManager"] = {}


def get_graph_ui_manager(workspace: Path) -> "GraphUiServerManager":
    """Get or create one graph UI manager per workspace path."""
    key = str(workspace.expanduser().resolve())
    manager = _MANAGERS.get(key)
    if manager is None:
        manager = GraphUiServerManager(workspace=Path(key))
        _MANAGERS[key] = manager
    return manager


class GraphUiRequestHandler(BaseHTTPRequestHandler):
    """Serve graph UI static files and a small JSON CRUD API."""

    server_version = "fagent-graph-ui/1.0"

    @property
    def graph_server(self) -> "GraphUiHttpServer":
        return self.server  # type: ignore[return-value]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_static("index.html", "text/html; charset=utf-8")
            return
        if parsed.path.startswith("/assets/"):
            asset_rel = parsed.path.removeprefix("/assets/")
            asset_root = (_STATIC_DIR / "assets").resolve()
            asset_path = (asset_root / asset_rel).resolve()
            if not str(asset_path).startswith(str(asset_root)) or not asset_path.exists():
                self._send_json({"error": "asset_not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            content_type = "application/octet-stream"
            if asset_path.suffix == ".js":
                content_type = "application/javascript; charset=utf-8"
            elif asset_path.suffix == ".css":
                content_type = "text/css; charset=utf-8"
            self._serve_static(f"assets/{asset_rel}", content_type)
            return
        if parsed.path == "/api/graph":
            params = parse_qs(parsed.query)
            payload = self.graph_server.orchestrator.export_graph_overview(
                query=_first(params.get("query")),
                session_key=_first(params.get("session")),
                mode=_first(params.get("mode")) or "global-clustered",
                node_limit=_int_or_default(_first(params.get("node_limit")), 200),
                edge_limit=_int_or_default(_first(params.get("edge_limit")), 400),
            )
            self._send_json(payload)
            return
        if parsed.path == "/api/graph/overview":
            params = parse_qs(parsed.query)
            payload = self.graph_server.orchestrator.export_graph_overview(
                query=_first(params.get("query")),
                session_key=_first(params.get("session")),
                mode=_first(params.get("mode")) or "global-clustered",
                node_limit=_int_or_default(_first(params.get("node_limit")), 200),
                edge_limit=_int_or_default(_first(params.get("edge_limit")), 400),
            )
            self._send_json(payload)
            return
        if parsed.path.startswith("/api/graph/focus/"):
            params = parse_qs(parsed.query)
            node_id = unquote(parsed.path.removeprefix("/api/graph/focus/"))
            payload = self.graph_server.orchestrator.export_graph_focus(
                node_id,
                query=_first(params.get("query")),
                session_key=_first(params.get("session")),
                node_limit=_int_or_default(_first(params.get("node_limit")), 200),
                edge_limit=_int_or_default(_first(params.get("edge_limit")), 400),
            )
            self._send_json(payload)
            return
        if parsed.path.startswith("/api/graph/details/"):
            params = parse_qs(parsed.query)
            node_id = unquote(parsed.path.removeprefix("/api/graph/details/"))
            payload = self.graph_server.orchestrator.export_graph_details(
                node_id,
                query=_first(params.get("query")),
                session_key=_first(params.get("session")),
                node_limit=_int_or_default(_first(params.get("node_limit")), 200),
                edge_limit=_int_or_default(_first(params.get("edge_limit")), 400),
            )
            self._send_json(payload)
            return
        if parsed.path.startswith("/api/graph/node/"):
            node_id = unquote(parsed.path.removeprefix("/api/graph/node/"))
            entity = self.graph_server.orchestrator.get_entity(node_id)
            if entity is None:
                self._send_json({"error": "node_not_found", "node_id": node_id}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(entity)
            return
        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/graph/nodes":
            data = self._read_json_body()
            payload = self.graph_server.orchestrator.upsert_graph_node(
                node_id=str(data["id"]),
                label=str(data.get("label") or data["id"]),
                metadata=_coerce_metadata(data.get("metadata_json"), data),
            )
            self._send_json(payload)
            return
        if parsed.path == "/api/graph/edges":
            data = self._read_json_body()
            payload = self.graph_server.orchestrator.upsert_graph_edge(
                source_id=str(data["source_id"]),
                target_id=str(data["target_id"]),
                relation=str(data["relation"]),
                weight=float(data.get("weight", 1.0)),
                metadata=_coerce_metadata(data.get("metadata_json"), data),
            )
            self._send_json(payload)
            return
        if parsed.path == "/api/graph/layouts":
            data = self._read_json_body()
            items = data.get("items") or []
            if not isinstance(items, list):
                self._send_json({"error": "invalid_layout_items"}, status=HTTPStatus.BAD_REQUEST)
                return
            payload = self.graph_server.orchestrator.save_graph_layouts(items)
            self._send_json(payload)
            return
        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def do_PATCH(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/graph/nodes/"):
            node_id = unquote(parsed.path.removeprefix("/api/graph/nodes/"))
            existing = self.graph_server.orchestrator.get_entity(node_id)
            if existing is None:
                self._send_json({"error": "node_not_found", "node_id": node_id}, status=HTTPStatus.NOT_FOUND)
                return
            data = self._read_json_body()
            metadata = dict(existing.get("metadata") or {})
            metadata.update(_coerce_metadata(data.get("metadata_json"), data))
            payload = self.graph_server.orchestrator.upsert_graph_node(
                node_id=node_id,
                label=str(data.get("label") or existing.get("label") or node_id),
                metadata=metadata,
            )
            self._send_json(payload)
            return
        if parsed.path.startswith("/api/graph/edges/"):
            parts = [unquote(item) for item in parsed.path.removeprefix("/api/graph/edges/").split("/")]
            if len(parts) != 3:
                self._send_json({"error": "invalid_edge_path"}, status=HTTPStatus.BAD_REQUEST)
                return
            source_id, relation, target_id = parts
            existing = self.graph_server.orchestrator.registry.get_graph_edge(source_id, target_id, relation)
            if existing is None:
                self._send_json({"error": "edge_not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            data = self._read_json_body()
            metadata = json.loads(existing["metadata_json"]) if existing["metadata_json"] else {}
            metadata.update(_coerce_metadata(data.get("metadata_json"), data))
            payload = self.graph_server.orchestrator.upsert_graph_edge(
                source_id=str(data.get("source_id") or source_id),
                target_id=str(data.get("target_id") or target_id),
                relation=str(data.get("relation") or relation),
                weight=float(data.get("weight", existing["weight"])),
                metadata=metadata,
            )
            if (
                str(data.get("source_id") or source_id) != source_id
                or str(data.get("target_id") or target_id) != target_id
                or str(data.get("relation") or relation) != relation
            ):
                self.graph_server.orchestrator.delete_graph_edge(source_id, target_id, relation)
            self._send_json(payload)
            return
        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/graph/nodes/"):
            node_id = unquote(parsed.path.removeprefix("/api/graph/nodes/"))
            payload = self.graph_server.orchestrator.delete_graph_node(node_id)
            self._send_json(payload)
            return
        if parsed.path.startswith("/api/graph/edges/"):
            parts = [unquote(item) for item in parsed.path.removeprefix("/api/graph/edges/").split("/")]
            if len(parts) != 3:
                self._send_json({"error": "invalid_edge_path"}, status=HTTPStatus.BAD_REQUEST)
                return
            source_id, relation, target_id = parts
            payload = self.graph_server.orchestrator.delete_graph_edge(source_id, target_id, relation)
            self._send_json(payload)
            return
        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def _serve_static(self, relative_path: str, content_type: str) -> None:
        path = (_STATIC_DIR / relative_path).resolve()
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        if not raw:
            return {}
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _send_json(self, payload: Any, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class GraphUiHttpServer(ThreadingHTTPServer):
    """HTTP server with attached orchestrator."""

    def __init__(self, server_address: tuple[str, int], orchestrator: MemoryOrchestrator):
        super().__init__(server_address, GraphUiRequestHandler)
        self.orchestrator = orchestrator


class GraphUiServerManager:
    """Lifecycle wrapper around the local graph UI server."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self._server: GraphUiHttpServer | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(
        self,
        orchestrator: MemoryOrchestrator,
        *,
        port: int = 0,
        query: str | None = None,
        session_key: str | None = None,
        open_browser: bool = True,
    ) -> str:
        if self._server is None:
            self._stop.clear()
            self._server = GraphUiHttpServer(("127.0.0.1", port), orchestrator)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="fagent-graph-ui")
            self._thread.start()
        url = self.url(query=query, session_key=session_key)
        if open_browser:
            webbrowser.open(url)
        return url

    def url(self, *, query: str | None = None, session_key: str | None = None) -> str:
        if self._server is None:
            raise RuntimeError("Graph UI server is not running")
        base = f"http://127.0.0.1:{self._server.server_address[1]}/"
        params: list[str] = []
        if query:
            params.append(f"query={quote(query)}")
        if session_key:
            params.append(f"session={quote(session_key)}")
        return base + (("?" + "&".join(params)) if params else "")

    def wait_forever(self) -> None:
        self._stop.wait()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        self._stop.set()


def _first(values: list[str] | None) -> str | None:
    return values[0] if values else None


def _int_or_default(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _coerce_metadata(metadata_json: object, payload: dict[str, Any]) -> dict[str, object]:
    if isinstance(metadata_json, str) and metadata_json.strip():
        loaded = json.loads(metadata_json)
        return loaded if isinstance(loaded, dict) else {}
    result: dict[str, object] = {}
    for key in ("kind", "confidence"):
        if key in payload:
            result[key] = payload[key]
    return result
