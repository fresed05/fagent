const url = new URL(window.location.href);
const params = url.searchParams;

const overviewNodes = new vis.DataSet([]);
const overviewEdges = new vis.DataSet([]);
const focusNodes = new vis.DataSet([]);
const focusEdges = new vis.DataSet([]);

const queryInput = document.getElementById("query");
const sessionInput = document.getElementById("session");
const modeSelect = document.getElementById("modeSelect");
const loadBtn = document.getElementById("loadBtn");
const fitOverviewBtn = document.getElementById("fitOverviewBtn");
const fitFocusBtn = document.getElementById("fitFocusBtn");
const refreshFocusBtn = document.getElementById("refreshFocusBtn");
const overviewStatus = document.getElementById("overviewStatus");
const focusStatus = document.getElementById("focusStatus");
const mapModeBadge = document.getElementById("mapModeBadge");
const mapStatsBadge = document.getElementById("mapStatsBadge");
const focusKindBadge = document.getElementById("focusKindBadge");
const focusStatsBadge = document.getElementById("focusStatsBadge");
const focusTitle = document.getElementById("focusTitle");
const detailsTitle = document.getElementById("detailsTitle");
const detailsKindBadge = document.getElementById("detailsKindBadge");
const detailsSummary = document.getElementById("detailsSummary");
const detailsMetadata = document.getElementById("detailsMetadata");
const detailsNeighbors = document.getElementById("detailsNeighbors");
const searchResults = document.getElementById("searchResults");
const nodeForm = document.getElementById("nodeForm");
const edgeForm = document.getElementById("edgeForm");
const resetNodeBtn = document.getElementById("resetNodeBtn");
const resetEdgeBtn = document.getElementById("resetEdgeBtn");

queryInput.value = params.get("query") || "";
sessionInput.value = params.get("session") || "";
modeSelect.value = params.get("mode") || "global-clustered";

const state = {
  overview: null,
  focus: null,
  details: null,
  selectedId: null,
  selectedKind: "idle",
};

const overviewNetwork = new vis.Network(
  document.getElementById("overviewNetwork"),
  { nodes: overviewNodes, edges: overviewEdges },
  {
    autoResize: true,
    physics: {
      enabled: true,
      stabilization: { enabled: true, iterations: 120 },
      solver: "forceAtlas2Based",
      forceAtlas2Based: { springLength: 110, damping: 0.8, gravitationalConstant: -30 },
    },
    interaction: { hover: true, navigationButtons: true, multiselect: false },
    nodes: {
      shape: "dot",
      size: 18,
      font: { face: "IBM Plex Sans", size: 13, color: "#edf4ff" },
      borderWidth: 2,
    },
    edges: {
      color: { color: "rgba(156, 184, 216, 0.32)", highlight: "#7cd6ff" },
      smooth: false,
      selectionWidth: 0,
      hoverWidth: 0.2,
    },
  }
);

const focusNetwork = new vis.Network(
  document.getElementById("focusNetwork"),
  { nodes: focusNodes, edges: focusEdges },
  {
    autoResize: true,
    physics: {
      enabled: true,
      stabilization: { enabled: true, iterations: 80 },
      solver: "forceAtlas2Based",
      forceAtlas2Based: { springLength: 140, damping: 0.82, gravitationalConstant: -42 },
    },
    interaction: { hover: true, navigationButtons: true, multiselect: false },
    nodes: {
      shape: "dot",
      size: 22,
      font: { face: "IBM Plex Sans", size: 14, color: "#edf4ff", multi: "md" },
      borderWidth: 2,
    },
    edges: {
      color: { color: "rgba(186, 214, 241, 0.56)", highlight: "#ff9b73" },
      smooth: { enabled: true, type: "continuous" },
      font: { face: "IBM Plex Sans", align: "middle", color: "#dcecff" },
    },
  }
);

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function secondaryLabel(parts) {
  return parts.filter(Boolean).join(" • ");
}

function apiUrl(path, extra = {}) {
  const qs = new URLSearchParams();
  const query = extra.query ?? queryInput.value.trim();
  const session = extra.session ?? sessionInput.value.trim();
  if (query) qs.set("query", query);
  if (session) qs.set("session", session);
  if (extra.mode) qs.set("mode", extra.mode);
  return `${path}${qs.toString() ? `?${qs.toString()}` : ""}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

function nodePalette(kind, isCluster = false) {
  if (isCluster) {
    return { background: "#3d3262", border: "#d4b5ff" };
  }
  if (kind === "entity") {
    return { background: "#163b34", border: "#69d8c0" };
  }
  if (kind === "fact") {
    return { background: "#4e2a24", border: "#ff9b73" };
  }
  if (kind === "episode") {
    return { background: "#18385e", border: "#78d6ff" };
  }
  return { background: "#17283f", border: "#8ba7c7" };
}

function priorityScore(node) {
  return Number((node.metadata || {}).priority_score || node.degree || 0);
}

function formatOverviewNode(node) {
  const metadata = node.metadata || {};
  const isCluster = !!metadata.is_cluster;
  const label = isCluster
    ? `${node.label}\n${metadata.cluster_size || 0}`
    : priorityScore(node) >= 6
      ? node.label
      : "";
  return {
    id: node.id,
    label,
    title: `${node.label}\n${JSON.stringify(metadata, null, 2)}`,
    shape: isCluster ? "hexagon" : metadata.kind === "fact" ? "box" : "dot",
    size: isCluster ? 26 : Math.max(16, 12 + Math.min(14, priorityScore(node))),
    color: nodePalette(metadata.kind || "node", isCluster),
    mass: isCluster ? 2.6 : 1.1,
    borderWidth: isCluster ? 3 : 2,
    font: { color: "#edf4ff", strokeWidth: 0, multi: "md" },
  };
}

function formatFocusNode(node) {
  const metadata = node.metadata || {};
  return {
    id: node.id,
    label: node.label,
    title: `${node.id}\n${JSON.stringify(metadata, null, 2)}`,
    shape: metadata.kind === "fact" ? "box" : "dot",
    size: metadata.selected ? 28 : 22,
    color: nodePalette(metadata.kind || "node", !!metadata.is_cluster),
    borderWidth: metadata.selected ? 4 : 2,
    font: { color: "#edf4ff", multi: "md" },
  };
}

function formatOverviewEdge(edge) {
  return {
    id: `${edge.source_id}|${edge.relation}|${edge.target_id}`,
    from: edge.source_id,
    to: edge.target_id,
    width: Math.max(1, Number(edge.weight || 1)),
    dashes: !!((edge.metadata || {}).is_aggregate),
    arrows: "to",
  };
}

function formatFocusEdge(edge) {
  const count = Number((edge.metadata || {}).member_edge_count || 1);
  return {
    id: `${edge.source_id}|${edge.relation}|${edge.target_id}`,
    from: edge.source_id,
    to: edge.target_id,
    label: count > 1 ? `${edge.relation} x${count}` : edge.relation,
    width: Math.max(1, Number(edge.weight || 1) + (count > 1 ? 1 : 0)),
    dashes: !!((edge.metadata || {}).is_aggregate),
    arrows: "to",
  };
}

function renderSearchResults(items) {
  if (!items || !items.length) {
    searchResults.textContent = "No ranked matches for the current scope.";
    return;
  }
  searchResults.innerHTML = items.map((item) => `
    <button class="resultItem" data-id="${escapeHtml(item.id)}" data-kind="${item.is_cluster ? "cluster" : item.kind}">
      <strong>${escapeHtml(item.label)}</strong>
      <span>${escapeHtml(item.is_cluster ? secondaryLabel(["cloud", `score ${item.priority_score}`]) : secondaryLabel([item.kind, `score ${item.priority_score}`]))}</span>
    </button>
  `).join("");
}

function renderOverview(payload) {
  state.overview = payload;
  overviewNodes.clear();
  overviewEdges.clear();
  overviewNodes.add((payload.nodes || []).map(formatOverviewNode));
  overviewEdges.add((payload.edges || []).map(formatOverviewEdge));
  mapModeBadge.textContent = payload.mode || "global-clustered";
  const hiddenNodes = Number(payload.hidden_node_count || 0);
  const hiddenEdges = Number(payload.hidden_edge_count || 0);
  mapStatsBadge.textContent = hiddenNodes || hiddenEdges
    ? `${(payload.nodes || []).length} nodes / ${(payload.edges || []).length} edges / ${hiddenNodes} hidden nodes`
    : `${(payload.nodes || []).length} nodes / ${(payload.edges || []).length} edges`;
  overviewStatus.textContent = payload.message || "Atlas loaded.";
  renderSearchResults(payload.search_results || []);
  setTimeout(() => overviewNetwork.stopSimulation(), payload.mode === "global-raw" ? 1200 : 500);
}

function renderFocus(payload) {
  state.focus = payload;
  focusNodes.clear();
  focusEdges.clear();
  focusNodes.add((payload.nodes || []).map(formatFocusNode));
  focusEdges.add((payload.edges || []).map(formatFocusEdge));
  focusTitle.textContent = payload.selected_id || "Workspace";
  focusKindBadge.textContent = payload.selected_kind || "idle";
  const hiddenMembers = Number((payload.summary || {}).cluster_size || 0);
  focusStatsBadge.textContent = hiddenMembers
    ? `${(payload.nodes || []).length} nodes / ${(payload.edges || []).length} edges / ${hiddenMembers} hidden`
    : `${(payload.nodes || []).length} nodes / ${(payload.edges || []).length} edges`;
  focusStatus.textContent = payload.message || "Focused neighborhood loaded.";
  refreshFocusBtn.disabled = !payload.selected_id;
  setTimeout(() => focusNetwork.stopSimulation(), 650);
}

function renderDetails(payload) {
  state.details = payload;
  detailsTitle.textContent = payload.title || payload.selected_id || "Inspector";
  detailsKindBadge.textContent = payload.kind || "idle";
  detailsSummary.textContent = payload.summary || "No summary available.";
  detailsMetadata.textContent = JSON.stringify(payload.metadata || {}, null, 2);
  const neighbors = payload.neighbors || [];
  const edges = payload.edges || [];
  const bridgeTargets = Array.isArray(payload.metadata?.cluster_bridge_targets)
    ? payload.metadata.cluster_bridge_targets
    : [];
  if (neighbors.length) {
    detailsNeighbors.innerHTML = neighbors.map((item) => `
      <button class="resultItem" data-id="${escapeHtml(item.id)}" data-kind="${escapeHtml((item.metadata || {}).kind || "node")}">
        <strong>${escapeHtml(item.label || item.id)}</strong>
        <span>${escapeHtml((item.metadata || {}).kind || "node")}</span>
      </button>
    `).join("");
  } else if (bridgeTargets.length) {
    detailsNeighbors.innerHTML = bridgeTargets.map((targetId) => `
      <button class="resultItem" data-id="${escapeHtml(targetId)}" data-kind="node">
        <strong>${escapeHtml(targetId)}</strong>
        <span>bridge target</span>
      </button>
    `).join("");
  } else if (edges.length) {
    detailsNeighbors.innerHTML = edges.map((item) => `
      <div class="resultItem">
        <strong>${escapeHtml(item.relation)}</strong>
        <span>${escapeHtml(`${item.source_id} -> ${item.target_id}`)}</span>
      </div>
    `).join("");
  } else {
    detailsNeighbors.textContent = "No neighborhood breakdown available.";
  }
}

async function loadOverview() {
  const payload = await api(apiUrl("/api/graph/overview", { mode: modeSelect.value }));
  renderOverview(payload);
  if (!state.selectedId && payload.search_results && payload.search_results.length) {
    await selectItem(payload.search_results[0].id);
  }
}

async function selectItem(nodeId) {
  state.selectedId = nodeId;
  const [focusPayload, detailsPayload] = await Promise.all([
    api(apiUrl(`/api/graph/focus/${encodeURIComponent(nodeId)}`)),
    api(apiUrl(`/api/graph/details/${encodeURIComponent(nodeId)}`)),
  ]);
  renderFocus(focusPayload);
  renderDetails(detailsPayload);
  syncForms(detailsPayload);
}

function syncForms(detailsPayload) {
  if (!detailsPayload || detailsPayload.kind === "cluster") {
    nodeForm.reset();
    edgeForm.reset();
    nodeForm.elements.metadata_json.value = "{}";
    edgeForm.elements.metadata_json.value = "{}";
    return;
  }
  const metadata = detailsPayload.metadata || {};
  nodeForm.elements.id.value = detailsPayload.selected_id || "";
  nodeForm.elements.label.value = detailsPayload.title || detailsPayload.selected_id || "";
  nodeForm.elements.kind.value = metadata.kind || "";
  nodeForm.elements.confidence.value = metadata.confidence ?? "";
  nodeForm.elements.metadata_json.value = JSON.stringify(metadata, null, 2);
}

function fitOverview() {
  overviewNetwork.fit({ animation: { duration: 420, easingFunction: "easeInOutQuad" } });
}

function fitFocus() {
  focusNetwork.fit({ animation: { duration: 420, easingFunction: "easeInOutQuad" } });
}

function resetNodeForm() {
  nodeForm.reset();
  nodeForm.elements.metadata_json.value = "{}";
}

function resetEdgeForm() {
  edgeForm.reset();
  edgeForm.elements.weight.value = "1";
  edgeForm.elements.metadata_json.value = "{}";
}

async function saveNode(event) {
  event.preventDefault();
  const body = {
    id: nodeForm.elements.id.value.trim(),
    label: nodeForm.elements.label.value.trim(),
    kind: nodeForm.elements.kind.value.trim(),
    confidence: nodeForm.elements.confidence.value ? Number(nodeForm.elements.confidence.value) : undefined,
    metadata_json: nodeForm.elements.metadata_json.value,
  };
  if (!body.id) return;
  const endpoint = state.selectedId === body.id ? `/api/graph/nodes/${encodeURIComponent(body.id)}` : "/api/graph/nodes";
  const method = state.selectedId === body.id ? "PATCH" : "POST";
  await api(endpoint, { method, body: JSON.stringify(body) });
  await loadOverview();
  await selectItem(body.id);
}

async function saveEdge(event) {
  event.preventDefault();
  const body = {
    source_id: edgeForm.elements.source_id.value.trim(),
    relation: edgeForm.elements.relation.value.trim(),
    target_id: edgeForm.elements.target_id.value.trim(),
    weight: Number(edgeForm.elements.weight.value || "1"),
    metadata_json: edgeForm.elements.metadata_json.value,
  };
  if (!body.source_id || !body.relation || !body.target_id) return;
  await api("/api/graph/edges", { method: "POST", body: JSON.stringify(body) });
  await loadOverview();
  if (state.selectedId) {
    await selectItem(state.selectedId);
  }
}

overviewNetwork.on("selectNode", async (event) => {
  const nodeId = event.nodes[0];
  await selectItem(nodeId);
});

focusNetwork.on("selectNode", async (event) => {
  const nodeId = event.nodes[0];
  await selectItem(nodeId);
});

searchResults.addEventListener("click", async (event) => {
  const button = event.target.closest(".resultItem");
  if (!button || !button.dataset.id) return;
  await selectItem(button.dataset.id);
});

detailsNeighbors.addEventListener("click", async (event) => {
  const button = event.target.closest(".resultItem");
  if (!button || !button.dataset.id) return;
  await selectItem(button.dataset.id);
});

loadBtn.addEventListener("click", () => loadOverview().catch(showError));
fitOverviewBtn.addEventListener("click", fitOverview);
fitFocusBtn.addEventListener("click", fitFocus);
refreshFocusBtn.addEventListener("click", () => {
  if (!state.selectedId) return;
  selectItem(state.selectedId).catch(showError);
});
modeSelect.addEventListener("change", () => loadOverview().catch(showError));
resetNodeBtn.addEventListener("click", resetNodeForm);
resetEdgeBtn.addEventListener("click", resetEdgeForm);
nodeForm.addEventListener("submit", (event) => saveNode(event).catch(showError));
edgeForm.addEventListener("submit", (event) => saveEdge(event).catch(showError));

queryInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    loadOverview().catch(showError);
  }
});

sessionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    loadOverview().catch(showError);
  }
});

function showError(error) {
  overviewStatus.textContent = `Error: ${error.message}`;
  focusStatus.textContent = "The focus workspace could not be updated.";
  detailsSummary.textContent = error.message;
}

resetNodeForm();
resetEdgeForm();
loadOverview().catch(showError);
