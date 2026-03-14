/**
 * API client for the fagent graph backend.
 * The backend runs on the same origin as the static files.
 */

import type { RawNode, RawEdge, GraphPayload, NodeDetails } from './graph-types'

export type GraphMode = 'global-clustered' | 'global-raw'

export interface OverviewParams {
  query?: string
  session?: string
  mode?: GraphMode
  node_limit?: number
  edge_limit?: number
}

export interface FocusPayload {
  view: string
  selected_id: string
  selected_kind?: string
  nodes: RawNode[]
  edges: RawEdge[]
  message?: string
  summary?: Record<string, unknown>
}

export interface NodeUpsertPayload {
  id: string
  label: string
  kind?: string
  confidence?: number
  metadata_json?: string
}

export interface EdgeUpsertPayload {
  source_id: string
  relation: string
  target_id: string
  weight?: number
  metadata_json?: string
}

function buildQueryString(params: Record<string, string | number | undefined | null>): string {
  const qs = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      qs.set(key, String(value))
    }
  }
  const str = qs.toString()
  return str ? `?${str}` : ''
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const payload = await response.json()
  if (!response.ok) {
    throw new Error((payload as { error?: string }).error || `HTTP ${response.status}`)
  }
  return payload as T
}

/** Fetch overview graph (atlas view) */
export async function fetchGraphOverview(params: OverviewParams = {}): Promise<GraphPayload> {
  const qs = buildQueryString({
    query: params.query,
    session: params.session,
    mode: params.mode ?? 'global-clustered',
    node_limit: params.node_limit,
    edge_limit: params.edge_limit,
  })
  return apiFetch<GraphPayload>(`/api/graph/overview${qs}`)
}

/** Fetch focused neighborhood around a node */
export async function fetchGraphFocus(
  nodeId: string,
  params: { query?: string; session?: string } = {}
): Promise<FocusPayload> {
  const qs = buildQueryString({ query: params.query, session: params.session })
  return apiFetch<FocusPayload>(`/api/graph/focus/${encodeURIComponent(nodeId)}${qs}`)
}

/** Fetch details panel data for a node */
export async function fetchGraphDetails(
  nodeId: string,
  params: { query?: string; session?: string } = {}
): Promise<NodeDetails> {
  const qs = buildQueryString({ query: params.query, session: params.session })
  return apiFetch<NodeDetails>(`/api/graph/details/${encodeURIComponent(nodeId)}${qs}`)
}

/** Create or update a node */
export async function upsertNode(data: NodeUpsertPayload): Promise<void> {
  const isUpdate = !!(data.id && data.id.trim())
  const method = isUpdate ? 'PATCH' : 'POST'
  const url = isUpdate
    ? `/api/graph/nodes/${encodeURIComponent(data.id)}`
    : '/api/graph/nodes'
  await apiFetch(url, { method, body: JSON.stringify(data) })
}

/** Delete a node by ID */
export async function deleteNode(nodeId: string): Promise<void> {
  await apiFetch(`/api/graph/nodes/${encodeURIComponent(nodeId)}`, { method: 'DELETE' })
}

/** Create or update an edge */
export async function upsertEdge(data: EdgeUpsertPayload): Promise<void> {
  await apiFetch('/api/graph/edges', { method: 'POST', body: JSON.stringify(data) })
}

/** Delete an edge by source/relation/target */
export async function deleteEdge(
  sourceId: string,
  relation: string,
  targetId: string
): Promise<void> {
  const path = [sourceId, relation, targetId].map(encodeURIComponent).join('/')
  await apiFetch(`/api/graph/edges/${path}`, { method: 'DELETE' })
}
