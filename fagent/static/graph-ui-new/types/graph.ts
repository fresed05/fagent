export type NodeKind = 'entity' | 'fact' | 'episode' | 'cluster' | 'bridge'

export interface GraphNode {
  id: string
  label: string
  kind: NodeKind
  confidence?: number
  metadata?: Record<string, unknown>
  degree?: number
  priority_score?: number
  is_cluster?: boolean
  cluster_size?: number
}

export interface GraphEdge {
  id: string
  source_id: string
  target_id: string
  relation: string
  weight?: number
  metadata?: Record<string, unknown>
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export type ViewMode = 'atlas' | 'raw'
