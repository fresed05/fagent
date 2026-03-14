import type { Node, Edge } from "@xyflow/react"

export type NodeKind = "entity" | "fact" | "episode" | "cluster" | "bridge"

export interface GraphNodeData {
  label: string
  kind: NodeKind
  priority: number
  confidence?: number
  isCluster?: boolean
  clusterSize?: number
  metadata?: Record<string, unknown>
  degree?: number
  // Optimization fields
  isExpanded?: boolean
  childIds?: string[]
  parentId?: string
  depth?: number
  // Visual state
  isVisible?: boolean
  lodLevel?: number // 0=full, 1=simplified, 2=dot only
}

export interface GraphEdgeData {
  relation: string
  weight: number
  isAggregate?: boolean
  memberCount?: number
  // Optimization fields
  isBundled?: boolean
  bundleId?: string
  originalEdges?: string[]
}

export type GraphNode = Node<GraphNodeData>
export type GraphEdge = Edge<GraphEdgeData>

export interface RawNode {
  id: string
  label: string
  metadata?: {
    kind?: NodeKind
    priority_score?: number
    confidence?: number
    is_cluster?: boolean
    cluster_size?: number
    parent_id?: string
    child_ids?: string[]
    [key: string]: unknown
  }
  degree?: number
}

export interface RawEdge {
  source_id: string
  target_id: string
  relation: string
  weight?: number
  metadata?: {
    is_aggregate?: boolean
    member_edge_count?: number
    [key: string]: unknown
  }
}

export interface GraphPayload {
  nodes: RawNode[]
  edges: RawEdge[]
  mode?: string
  message?: string
  hidden_node_count?: number
  hidden_edge_count?: number
  search_results?: Array<{
    id: string
    label: string
    kind?: NodeKind
    is_cluster?: boolean
    priority_score?: number
  }>
}

export interface NodeDetails {
  selected_id: string
  title: string
  kind: NodeKind
  summary?: string
  metadata?: Record<string, unknown>
  neighbors?: RawNode[]
  edges?: RawEdge[]
}

// Cluster info for virtualization
export interface ClusterInfo {
  id: string
  nodeIds: Set<string>
  center: { x: number; y: number }
  radius: number
  isExpanded: boolean
}

// Viewport for virtualization
export interface ViewportBounds {
  x: number
  y: number
  width: number
  height: number
  zoom: number
}

// Color palette matching Obsidian aesthetic
export const NODE_COLORS: Record<NodeKind, { bg: string; border: string; glow: string }> = {
  entity: { bg: "#10b981", border: "#34d399", glow: "rgba(16, 185, 129, 0.4)" },
  fact: { bg: "#f97316", border: "#fb923c", glow: "rgba(249, 115, 22, 0.4)" },
  episode: { bg: "#3b82f6", border: "#60a5fa", glow: "rgba(59, 130, 246, 0.4)" },
  cluster: { bg: "#a855f7", border: "#c084fc", glow: "rgba(168, 85, 247, 0.4)" },
  bridge: { bg: "#6b7280", border: "#9ca3af", glow: "rgba(107, 114, 128, 0.4)" },
}

// LOD thresholds
export const LOD_THRESHOLDS = {
  FULL_DETAIL: 0.5,      // Show all details above this zoom
  SIMPLIFIED: 0.2,        // Show simplified nodes between this and full
  DOT_ONLY: 0.08,         // Show only dots below simplified
  HIDE_EDGES: 0.05,       // Hide most edges below this
}

// Performance thresholds
export const PERFORMANCE_CONFIG = {
  MAX_VISIBLE_NODES: 500,
  MAX_VISIBLE_EDGES: 1000,
  CLUSTER_THRESHOLD: 50,  // Auto-cluster when this many nodes in view
  EDGE_BUNDLE_THRESHOLD: 10, // Bundle edges when node has more than this
}
