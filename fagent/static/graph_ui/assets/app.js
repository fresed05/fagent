const url = new URL(window.location.href);
const params = url.searchParams;

const nodes = new vis.DataSet([]);
const edges = new vis.DataSet([]);

const queryInput = document.getElementById("query");
const sessionInput = document.getElementById("session");
const loadBtn = document.getElementById("loadBtn");
const focusBtn = document.getElementById("focusBtn");
const fitBtn = document.getElementById("fitBtn");
const physicsBtn = document.getElementById("physicsBtn");
const saveLayoutBtn = document.getElementById("saveLayoutBtn");
const inspector = document.getElementById("inspector");
const expandBtn = document.getElementById("expandBtn");
const deleteSelectedBtn = document.getElementById("deleteSelectedBtn");
const nodeCount = document.getElementById("nodeCount");
const edgeCount = document.getElementById("edgeCount");
const queryState = document.getElementById("queryState");
const selectionBadge = document.getElementById("selectionBadge");
const statusBanner = document.getElementById("statusBanner");
const nodeForm = document.getElementById("nodeForm");
const edgeForm = document.getElementById("edgeForm");
const resetNodeBtn = document.getElementById("resetNodeBtn");
const resetEdgeBtn = document.getElementById("resetEdgeBtn");

queryInput.value = params.get("query") || "";
sessionInput.value = params.get("session") || "";

let physicsEnabled = true;
let selected = { type: null, id: null };

const network = new vis.Network(
  document.getElementById("network"),
  { nodes, edges },
  {
    autoResize: true,
    physics: { enabled: true, stabilization: false },
    interaction: { hover: true, navigationButtons: true, multiselect: false },
    nodes: {
      shape: "dot",
      size: 20,
      font: { face: "IBM Plex Sans", size: 14, color: "#edf4ff" },
      borderWidth: 2,
      shadow: {
        enabled: true,
        color: "rgba(0, 0, 0, 0.24)",
        x: 0,
        y: 8,
        size: 24
      },
      color: {
        border: "#b0c9e9",
        background: "#10243b",
        highlight: { border: "#62d0ff", background: "#143658" }
      }
    },
    edges: {
      arrows: { to: { enabled: true, scaleFactor: 0.65 } },
      color: { color: "rgba(190, 214, 240, 0.56)", highlight: "#ff9966" },
      font: {
        face: "IBM Plex Sans",
        align: "middle",
        color: "#dcecff",
        strokeWidth: 6,
        strokeColor: "rgba(7, 17, 31, 0.72)"
      },
      smooth: {
        enabled: true,
        type: "dynamic"
      }
    }
  }
);

function nodeKindColor(kind) {
  switch (kind) {
    case "episode":
      return { background: "#17355e", border: "#62d0ff" };
    case "fact":
      return { background: "#4c2531", border: "#ff9966" };
    case "entity":
      return { background: "#18392d", border: "#7ef0b3" };
    default:
      return { background: "#10243b", border: "#b0c9e9" };
  }
}

function formatNode(row) {
  const metadata = row.metadata || {};
  const kind = metadata.kind || "node";
  const color = nodeKindColor(kind);
  const visNode = {
    id: row.id,
    label: row.label,
    title: `${row.id}\n${JSON.stringify(metadata, null, 2)}`,
    color,
    shape: metadata.kind === "fact" ? "box" : "dot",
    font: { color: "#edf4ff" }
  };
  if (row.layout) {
    visNode.x = row.layout.x;
    visNode.y = row.layout.y;
    visNode.fixed = !!row.layout.pinned;
  }
  return visNode;
}

function formatEdge(row) {
  return {
    id: `${row.source_id}|${row.relation}|${row.target_id}`,
    from: row.source_id,
    to: row.target_id,
    label: row.relation,
    arrows: "to",
    width: Math.max(1, Number(row.weight || 1))
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

function setStatus(message) {
  statusBanner.textContent = message;
}

function updateStats(payload) {
  nodeCount.textContent = String((payload.nodes || []).length);
  edgeCount.textContent = String((payload.edges || []).length);
  queryState.textContent = queryInput.value.trim() || "latest";
}

function formatMetadata(metadata) {
  return JSON.stringify(metadata || {}, null, 2);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function renderInspectorEmpty(message = "Select a node or edge") {
  inspector.className = "inspector empty";
  inspector.textContent = message;
  selectionBadge.textContent = "Idle";
}

function renderGraphSummary(payload) {
  inspector.className = "inspector";
  selectionBadge.textContent = "Graph";
  inspector.innerHTML = `
    <div class="inspectorCard">
      <div class="inspectorTitleRow">
        <h3 class="inspectorTitle">Current view</h3>
        <span class="inspectorKind">${queryInput.value.trim() ? "filtered" : "latest"}</span>
      </div>
      <div class="kvGrid">
        <div class="kvItem"><span>Nodes</span><strong>${payload.nodes.length}</strong></div>
        <div class="kvItem"><span>Edges</span><strong>${payload.edges.length}</strong></div>
      </div>
      <pre class="inspectorMeta">${escapeHtml(JSON.stringify({
        query: queryInput.value.trim() || null,
        session: sessionInput.value.trim() || null
      }, null, 2))}</pre>
    </div>
  `;
}

function renderNodeInspector(payload) {
  const kind = payload.metadata?.kind || "node";
  inspector.className = "inspector";
  selectionBadge.textContent = "Node";
  inspector.innerHTML = `
    <div class="inspectorCard">
      <div class="inspectorTitleRow">
        <h3 class="inspectorTitle">${escapeHtml(payload.label || payload.id)}</h3>
        <span class="inspectorKind">${escapeHtml(kind)}</span>
      </div>
      <div class="kvGrid">
        <div class="kvItem"><span>ID</span><strong>${escapeHtml(payload.id)}</strong></div>
        <div class="kvItem"><span>Neighbors</span><strong>${(payload.neighbors || []).length}</strong></div>
      </div>
      <pre class="inspectorMeta">${escapeHtml(formatMetadata(payload.metadata))}</pre>
    </div>
  `;
}

function renderEdgeInspector(payload, metadata = {}) {
  inspector.className = "inspector";
  selectionBadge.textContent = "Edge";
  inspector.innerHTML = `
    <div class="inspectorCard">
      <div class="inspectorTitleRow">
        <h3 class="inspectorTitle">${escapeHtml(payload.relation)}</h3>
        <span class="inspectorKind">edge</span>
      </div>
      <div class="kvGrid">
        <div class="kvItem"><span>Source</span><strong>${escapeHtml(payload.source_id)}</strong></div>
        <div class="kvItem"><span>Target</span><strong>${escapeHtml(payload.target_id)}</strong></div>
      </div>
      <pre class="inspectorMeta">${escapeHtml(formatMetadata(metadata))}</pre>
    </div>
  `;
}

function showError(err) {
  selectionBadge.textContent = "Error";
  inspector.className = "inspector";
  inspector.innerHTML = `<div class="inspectorCard"><h3 class="inspectorTitle">Request failed</h3><pre class="inspectorMeta">${escapeHtml(err.message)}</pre></div>`;
  setStatus(`Error: ${err.message}`);
}

async function loadGraph() {
  setStatus("Loading graph snapshot...");
  const query = queryInput.value.trim();
  const session = sessionInput.value.trim();
  const qs = new URLSearchParams();
  if (query) qs.set("query", query);
  if (session) qs.set("session", session);
  const payload = await api(`/api/graph?${qs.toString()}`);
  nodes.clear();
  edges.clear();
  nodes.add(payload.nodes.map(formatNode));
  edges.add(payload.edges.map(formatEdge));
  updateStats(payload);
  network.fit({ animation: { duration: 550, easingFunction: "easeInOutQuad" } });
  renderGraphSummary(payload);
  setStatus(
    payload.message || (
      payload.nodes.length
        ? "Graph loaded. Select a node to inspect details or expand its neighborhood."
        : "No graph items matched. Try a broader query or create a new node."
    )
  );
}

function resetNodeForm() {
  nodeForm.reset();
  nodeForm.elements.metadata_json.value = "{}";
  selected = { type: null, id: null };
  expandBtn.disabled = true;
  deleteSelectedBtn.disabled = true;
  renderInspectorEmpty();
}

function resetEdgeForm() {
  edgeForm.reset();
  edgeForm.elements.weight.value = "1";
  edgeForm.elements.metadata_json.value = "{}";
}

async function expandSelectedNode() {
  if (selected.type !== "node" || !selected.id) return;
  const payload = await api(`/api/graph/node/${encodeURIComponent(selected.id)}`);
  const neighborNodes = payload.neighbors || [];
  nodes.update([{ id: payload.id, label: payload.label }, ...neighborNodes.map(formatNode)]);
  edges.update((payload.edges || []).map((edge) => ({
    id: `${edge.source_id}|${edge.relation}|${edge.target_id}`,
    from: edge.source_id,
    to: edge.target_id,
    label: edge.relation,
    width: Math.max(1, Number(edge.weight || 1))
  })));
  updateStats({ nodes: nodes.get(), edges: edges.get() });
  network.focus(selected.id, { scale: 1.08, animation: { duration: 480, easingFunction: "easeInOutQuad" } });
  renderNodeInspector(payload);
  setStatus(`Expanded neighborhood for ${selected.id}.`);
}

async function savePositions() {
  const positions = network.getPositions();
  const items = Object.entries(positions).map(([nodeId, pos]) => ({
    node_id: nodeId,
    x: pos.x,
    y: pos.y,
    pinned: false
  }));
  const payload = await api("/api/graph/layouts", {
    method: "POST",
    body: JSON.stringify({ items })
  });
  setStatus(`Saved ${payload.saved || items.length} node positions.`);
}

function findBestMatchingNode() {
  const query = queryInput.value.trim().toLowerCase();
  if (!query) return null;
  return nodes.get().find((node) => {
    const label = String(node.label || "").toLowerCase();
    const id = String(node.id || "").toLowerCase();
    return id.includes(query) || label.includes(query);
  }) || null;
}

function focusBestMatch() {
  const match = findBestMatchingNode();
  if (!match) {
    setStatus("No visible node matched the current search.");
    return;
  }
  network.selectNodes([match.id]);
  network.focus(match.id, { scale: 1.16, animation: { duration: 480, easingFunction: "easeInOutQuad" } });
  setStatus(`Focused ${match.id}.`);
}

network.on("selectNode", async (event) => {
  selected = { type: "node", id: event.nodes[0] };
  expandBtn.disabled = false;
  deleteSelectedBtn.disabled = false;
  const payload = await api(`/api/graph/node/${encodeURIComponent(selected.id)}`);
  nodeForm.elements.id.value = payload.id;
  nodeForm.elements.label.value = payload.label;
  nodeForm.elements.kind.value = payload.metadata?.kind || "";
  nodeForm.elements.confidence.value = payload.metadata?.confidence ?? "";
  nodeForm.elements.metadata_json.value = JSON.stringify(payload.metadata || {}, null, 2);
  renderNodeInspector(payload);
  setStatus(`Selected node ${payload.id}.`);
});

network.on("selectEdge", (event) => {
  const edgeId = event.edges[0];
  selected = { type: "edge", id: edgeId };
  expandBtn.disabled = true;
  deleteSelectedBtn.disabled = false;
  const [sourceId, relation, targetId] = edgeId.split("|");
  edgeForm.elements.source_id.value = sourceId;
  edgeForm.elements.relation.value = relation;
  edgeForm.elements.target_id.value = targetId;
  const edge = edges.get(edgeId);
  edgeForm.elements.weight.value = edge.width || 1;
  edgeForm.elements.metadata_json.value = "{}";
  renderEdgeInspector({ source_id: sourceId, relation, target_id: targetId }, {});
  setStatus(`Selected edge ${relation}.`);
});

network.on("deselectNode", resetNodeForm);
network.on("deselectEdge", () => {
  if (selected.type === "edge") {
    selected = { type: null, id: null };
    deleteSelectedBtn.disabled = true;
    resetEdgeForm();
    renderInspectorEmpty();
  }
});

loadBtn.addEventListener("click", () => loadGraph().catch(showError));
focusBtn.addEventListener("click", focusBestMatch);
fitBtn.addEventListener("click", () => network.fit({ animation: { duration: 420, easingFunction: "easeInOutQuad" } }));
physicsBtn.addEventListener("click", () => {
  physicsEnabled = !physicsEnabled;
  network.setOptions({ physics: { enabled: physicsEnabled, stabilization: false } });
  physicsBtn.textContent = `Physics: ${physicsEnabled ? "on" : "off"}`;
  setStatus(`Physics ${physicsEnabled ? "enabled" : "disabled"}.`);
});
saveLayoutBtn.addEventListener("click", () => savePositions().catch(showError));
expandBtn.addEventListener("click", () => expandSelectedNode().catch(showError));
resetNodeBtn.addEventListener("click", resetNodeForm);
resetEdgeBtn.addEventListener("click", resetEdgeForm);

queryInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    loadGraph().catch(showError);
  }
});

sessionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    loadGraph().catch(showError);
  }
});

deleteSelectedBtn.addEventListener("click", async () => {
  if (!selected.type || !selected.id) return;
  try {
    if (selected.type === "node") {
      await api(`/api/graph/nodes/${encodeURIComponent(selected.id)}`, { method: "DELETE" });
      nodes.remove(selected.id);
      edges.remove(edges.getIds().filter((id) => id.startsWith(`${selected.id}|`) || id.endsWith(`|${selected.id}`)));
      updateStats({ nodes: nodes.get(), edges: edges.get() });
      setStatus(`Deleted node ${selected.id}.`);
      resetNodeForm();
    } else {
      const [sourceId, relation, targetId] = selected.id.split("|");
      await api(`/api/graph/edges/${encodeURIComponent(sourceId)}/${encodeURIComponent(relation)}/${encodeURIComponent(targetId)}`, { method: "DELETE" });
      edges.remove(selected.id);
      updateStats({ nodes: nodes.get(), edges: edges.get() });
      setStatus(`Deleted edge ${relation}.`);
      resetEdgeForm();
      renderInspectorEmpty();
    }
  } catch (err) {
    showError(err);
  }
});

nodeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = {
    id: nodeForm.elements.id.value.trim(),
    label: nodeForm.elements.label.value.trim(),
    kind: nodeForm.elements.kind.value.trim(),
    confidence: nodeForm.elements.confidence.value ? Number(nodeForm.elements.confidence.value) : undefined,
    metadata_json: nodeForm.elements.metadata_json.value
  };
  try {
    const method = selected.type === "node" && selected.id === body.id ? "PATCH" : "POST";
    const endpoint = method === "PATCH"
      ? `/api/graph/nodes/${encodeURIComponent(body.id)}`
      : "/api/graph/nodes";
    const payload = await api(endpoint, { method, body: JSON.stringify(body) });
    nodes.update([formatNode(payload.node)]);
    updateStats({ nodes: nodes.get(), edges: edges.get() });
    renderNodeInspector(payload.node);
    setStatus(`Saved node ${payload.node.id}.`);
  } catch (err) {
    showError(err);
  }
});

edgeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = {
    source_id: edgeForm.elements.source_id.value.trim(),
    relation: edgeForm.elements.relation.value.trim(),
    target_id: edgeForm.elements.target_id.value.trim(),
    weight: Number(edgeForm.elements.weight.value || "1"),
    metadata_json: edgeForm.elements.metadata_json.value
  };
  const edgeId = `${body.source_id}|${body.relation}|${body.target_id}`;
  const method = selected.type === "edge" && selected.id === edgeId ? "PATCH" : "POST";
  const endpoint = method === "PATCH"
    ? (() => {
        const [sourceId, relation, targetId] = selected.id.split("|");
        return `/api/graph/edges/${encodeURIComponent(sourceId)}/${encodeURIComponent(relation)}/${encodeURIComponent(targetId)}`;
      })()
    : "/api/graph/edges";
  try {
    const payload = await api(endpoint, { method, body: JSON.stringify(body) });
    edges.update([{ id: edgeId, from: body.source_id, to: body.target_id, label: body.relation, width: Math.max(1, body.weight) }]);
    updateStats({ nodes: nodes.get(), edges: edges.get() });
    renderEdgeInspector(body, payload.edge?.metadata || {});
    setStatus(`Saved edge ${body.relation}.`);
  } catch (err) {
    showError(err);
  }
});

renderInspectorEmpty();
loadGraph().catch(showError);
