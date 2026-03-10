const url = new URL(window.location.href);
const params = url.searchParams;

const nodes = new vis.DataSet([]);
const edges = new vis.DataSet([]);

const queryInput = document.getElementById("query");
const sessionInput = document.getElementById("session");
const loadBtn = document.getElementById("loadBtn");
const fitBtn = document.getElementById("fitBtn");
const physicsBtn = document.getElementById("physicsBtn");
const saveLayoutBtn = document.getElementById("saveLayoutBtn");
const inspector = document.getElementById("inspector");
const expandBtn = document.getElementById("expandBtn");
const deleteSelectedBtn = document.getElementById("deleteSelectedBtn");
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
      size: 18,
      font: { face: "IBM Plex Sans", size: 14 },
      borderWidth: 2,
      color: {
        border: "#1d241f",
        background: "#fef4d7",
        highlight: { border: "#155eef", background: "#dbe7ff" }
      }
    },
    edges: {
      arrows: { to: { enabled: true, scaleFactor: 0.65 } },
      color: { color: "#677369", highlight: "#b93815" },
      font: { face: "IBM Plex Sans", align: "middle", strokeWidth: 0 }
    }
  }
);

function nodeKindColor(kind) {
  switch (kind) {
    case "episode":
      return { background: "#dceafe", border: "#155eef" };
    case "fact":
      return { background: "#ffe2d6", border: "#b93815" };
    case "entity":
      return { background: "#e6f6df", border: "#2f6b2f" };
    default:
      return { background: "#fef4d7", border: "#1d241f" };
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
    shape: metadata.kind === "fact" ? "box" : "dot"
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

async function loadGraph() {
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
  network.fit({ animation: true });
  setInspector("Loaded graph", payload);
}

function setInspector(title, payload) {
  inspector.classList.remove("empty");
  inspector.textContent = `${title}\n\n${JSON.stringify(payload, null, 2)}`;
}

function resetNodeForm() {
  nodeForm.reset();
  nodeForm.elements.metadata_json.value = "{}";
  selected = { type: null, id: null };
  expandBtn.disabled = true;
  deleteSelectedBtn.disabled = true;
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
  network.focus(selected.id, { scale: 1.1, animation: true });
  setInspector("Expanded node", payload);
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
  setInspector("Saved positions", payload);
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
  setInspector("Node", payload);
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
  setInspector("Edge", { source_id: sourceId, relation, target_id: targetId });
});

network.on("deselectNode", () => {
  if (selected.type === "node") {
    resetNodeForm();
  }
});

loadBtn.addEventListener("click", () => loadGraph().catch((err) => setInspector("Error", { error: err.message })));
fitBtn.addEventListener("click", () => network.fit({ animation: true }));
physicsBtn.addEventListener("click", () => {
  physicsEnabled = !physicsEnabled;
  network.setOptions({ physics: { enabled: physicsEnabled, stabilization: false } });
  physicsBtn.textContent = `Physics: ${physicsEnabled ? "on" : "off"}`;
});
saveLayoutBtn.addEventListener("click", () => savePositions().catch((err) => setInspector("Error", { error: err.message })));
expandBtn.addEventListener("click", () => expandSelectedNode().catch((err) => setInspector("Error", { error: err.message })));
resetNodeBtn.addEventListener("click", resetNodeForm);
resetEdgeBtn.addEventListener("click", resetEdgeForm);

deleteSelectedBtn.addEventListener("click", async () => {
  if (!selected.type || !selected.id) return;
  try {
    if (selected.type === "node") {
      const payload = await api(`/api/graph/nodes/${encodeURIComponent(selected.id)}`, { method: "DELETE" });
      nodes.remove(selected.id);
      edges.remove(edges.getIds().filter((id) => id.startsWith(`${selected.id}|`) || id.endsWith(`|${selected.id}`)));
      setInspector("Deleted node", payload);
      resetNodeForm();
    } else {
      const [sourceId, relation, targetId] = selected.id.split("|");
      const payload = await api(`/api/graph/edges/${encodeURIComponent(sourceId)}/${encodeURIComponent(relation)}/${encodeURIComponent(targetId)}`, { method: "DELETE" });
      edges.remove(selected.id);
      setInspector("Deleted edge", payload);
      resetEdgeForm();
    }
  } catch (err) {
    setInspector("Error", { error: err.message });
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
    setInspector("Saved node", payload);
  } catch (err) {
    setInspector("Error", { error: err.message });
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
    setInspector("Saved edge", payload);
  } catch (err) {
    setInspector("Error", { error: err.message });
  }
});

loadGraph().catch((err) => setInspector("Error", { error: err.message }));
