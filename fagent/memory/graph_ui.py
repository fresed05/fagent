"""Local graph UI HTTP server and per-workspace server manager."""

from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from fagent.memory.orchestrator import MemoryOrchestrator


# Compiled Next.js static export lives at graph-ui-new/out/
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "graph-ui-new" / "out"
_MANAGERS: dict[str, "GraphUiServerManager"] = {}

# Explicit MIME type overrides (supplement system mimetypes)
_MIME_OVERRIDES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".map": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _MIME_OVERRIDES:
        return _MIME_OVERRIDES[suffix]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


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

    server_version = "fagent-graph-ui/2.0"

    @property
    def graph_server(self) -> "GraphUiHttpServer":
        return self.server  # type: ignore[return-value]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    # ------------------------------------------------------------------
    # CORS preflight
    # ------------------------------------------------------------------

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    # ------------------------------------------------------------------
    # GET
    # ------------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._handle_get()
        except Exception:  # noqa: BLE001
            try:
                self._send_json({"error": "internal_error"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            except Exception:  # noqa: BLE001
                pass

    def _handle_get(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        # ----- API routes (unchanged) -----
        if path == "/api/graph" or path == "/api/graph/overview":
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

        if path.startswith("/api/graph/focus/"):
            params = parse_qs(parsed.query)
            node_id = unquote(path.removeprefix("/api/graph/focus/"))
            payload = self.graph_server.orchestrator.export_graph_focus(
                node_id,
                query=_first(params.get("query")),
                session_key=_first(params.get("session")),
                node_limit=_int_or_default(_first(params.get("node_limit")), 200),
                edge_limit=_int_or_default(_first(params.get("edge_limit")), 400),
            )
            self._send_json(payload)
            return

        if path.startswith("/api/graph/details/"):
            params = parse_qs(parsed.query)
            node_id = unquote(path.removeprefix("/api/graph/details/"))
            payload = self.graph_server.orchestrator.export_graph_details(
                node_id,
                query=_first(params.get("query")),
                session_key=_first(params.get("session")),
                node_limit=_int_or_default(_first(params.get("node_limit")), 200),
                edge_limit=_int_or_default(_first(params.get("edge_limit")), 400),
            )
            self._send_json(payload)
            return

        if path.startswith("/api/graph/node/"):
            node_id = unquote(path.removeprefix("/api/graph/node/"))
            entity = self.graph_server.orchestrator.get_entity(node_id)
            if entity is None:
                self._send_json({"error": "node_not_found", "node_id": node_id}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(entity)
            return

        # ----- Static file serving (Next.js export) -----
        self._serve_static_path(path)

    def _serve_static_path(self, url_path: str) -> None:
        """Resolve a URL path to a file in _STATIC_DIR and serve it.

        Falls back to index.html for SPA navigation (client-side routing).
        With `trailingSlash: true` in next.config.mjs, Next.js generates
        /foo/index.html for each route, but we also handle the bare /foo case.
        """
        # Normalise: strip leading slash, default to index.html
        relative = url_path.lstrip("/") or "index.html"

        candidate = (_STATIC_DIR / relative).resolve()

        # Security check: must stay within _STATIC_DIR
        try:
            candidate.relative_to(_STATIC_DIR)
        except ValueError:
            self._send_json({"error": "forbidden"}, status=HTTPStatus.FORBIDDEN)
            return

        # Try exact path first
        if candidate.is_file():
            self._serve_file(candidate)
            return

        # Try appending index.html (trailingSlash behaviour)
        index_candidate = candidate / "index.html"
        if index_candidate.is_file():
            self._serve_file(index_candidate)
            return

        # Do NOT SPA-fallback for asset paths — return 404 to avoid
        # the browser misinterpreting an HTML page as JavaScript/CSS.
        _NO_SPA_PREFIXES = ("/_next/", "/_vercel/", "/static/", "/favicon")
        if any(url_path.startswith(p) for p in _NO_SPA_PREFIXES):
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return

        # Also do not SPA-fallback for requests with known asset extensions
        _ASSET_EXTS = {".js", ".mjs", ".css", ".map", ".woff", ".woff2", ".ttf", ".ico", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
        suffix = Path(url_path.split("?")[0]).suffix.lower()
        if suffix in _ASSET_EXTS:
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return

        # SPA fallback: serve root index.html for unknown HTML routes
        root_index = _STATIC_DIR / "index.html"
        if root_index.is_file():
            self._serve_file(root_index)
            return

        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def _serve_file(self, path: Path) -> None:
        body = path.read_bytes()
        ct = _content_type(path)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        # Cache control: aggressive caching for _next/static (hashed filenames),
        # no-cache for HTML (SPA entry points)
        if "/_next/static/" in path.as_posix():
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Cache-Control", "no-cache")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------
    # POST
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # PATCH
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
        self._send_cors_headers()
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
        port: int = 8765,
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
