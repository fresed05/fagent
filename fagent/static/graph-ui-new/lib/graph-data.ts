'use client'

import { GraphNode, GraphEdge, GraphData, NodeKind } from '@/types/graph'

// Mock data generator
export function generateMockData(): GraphData {
  const entities: GraphNode[] = [
    { id: 'user-1', label: 'John Doe', kind: 'entity', confidence: 0.95, priority_score: 8, degree: 12 },
    { id: 'user-2', label: 'Jane Smith', kind: 'entity', confidence: 0.92, priority_score: 7, degree: 8 },
    { id: 'org-1', label: 'Acme Corp', kind: 'entity', confidence: 0.98, priority_score: 9, degree: 15 },
    { id: 'project-1', label: 'Alpha Project', kind: 'entity', confidence: 0.88, priority_score: 6, degree: 10 },
    { id: 'tech-1', label: 'React', kind: 'entity', confidence: 0.99, priority_score: 8, degree: 20 },
    { id: 'tech-2', label: 'TypeScript', kind: 'entity', confidence: 0.99, priority_score: 8, degree: 18 },
    { id: 'concept-1', label: 'Machine Learning', kind: 'entity', confidence: 0.85, priority_score: 7, degree: 14 },
  ]

  const facts: GraphNode[] = [
    { id: 'fact-1', label: 'CEO of Acme Corp', kind: 'fact', confidence: 0.9, priority_score: 5, degree: 3 },
    { id: 'fact-2', label: 'Works on Alpha', kind: 'fact', confidence: 0.87, priority_score: 4, degree: 4 },
    { id: 'fact-3', label: 'Expert in ML', kind: 'fact', confidence: 0.82, priority_score: 5, degree: 3 },
    { id: 'fact-4', label: 'Built with React', kind: 'fact', confidence: 0.95, priority_score: 4, degree: 2 },
    { id: 'fact-5', label: 'Founded in 2020', kind: 'fact', confidence: 0.98, priority_score: 3, degree: 2 },
  ]

  const episodes: GraphNode[] = [
    { id: 'ep-1', label: 'Meeting 2024-01', kind: 'episode', confidence: 0.75, priority_score: 3, degree: 5 },
    { id: 'ep-2', label: 'Code Review', kind: 'episode', confidence: 0.8, priority_score: 4, degree: 4 },
    { id: 'ep-3', label: 'Product Launch', kind: 'episode', confidence: 0.85, priority_score: 6, degree: 8 },
  ]

  const clusters: GraphNode[] = [
    { id: 'cluster-1', label: 'People', kind: 'cluster', is_cluster: true, cluster_size: 25, priority_score: 9, degree: 30 },
    { id: 'cluster-2', label: 'Technologies', kind: 'cluster', is_cluster: true, cluster_size: 18, priority_score: 8, degree: 22 },
    { id: 'cluster-3', label: 'Projects', kind: 'cluster', is_cluster: true, cluster_size: 12, priority_score: 7, degree: 15 },
  ]

  const bridges: GraphNode[] = [
    { id: 'bridge-1', label: 'Tech-People', kind: 'bridge', priority_score: 6, degree: 8 },
  ]

  const nodes = [...entities, ...facts, ...episodes, ...clusters, ...bridges]

  const edges: GraphEdge[] = [
    { id: 'e1', source_id: 'user-1', target_id: 'fact-1', relation: 'has_role', weight: 1 },
    { id: 'e2', source_id: 'fact-1', target_id: 'org-1', relation: 'at_org', weight: 1 },
    { id: 'e3', source_id: 'user-2', target_id: 'fact-2', relation: 'performs', weight: 1 },
    { id: 'e4', source_id: 'fact-2', target_id: 'project-1', relation: 'on_project', weight: 1 },
    { id: 'e5', source_id: 'user-1', target_id: 'fact-3', relation: 'has_skill', weight: 1 },
    { id: 'e6', source_id: 'fact-3', target_id: 'concept-1', relation: 'related_to', weight: 1 },
    { id: 'e7', source_id: 'project-1', target_id: 'fact-4', relation: 'uses', weight: 1 },
    { id: 'e8', source_id: 'fact-4', target_id: 'tech-1', relation: 'technology', weight: 1 },
    { id: 'e9', source_id: 'tech-1', target_id: 'tech-2', relation: 'pairs_with', weight: 0.8 },
    { id: 'e10', source_id: 'org-1', target_id: 'fact-5', relation: 'has_attribute', weight: 1 },
    { id: 'e11', source_id: 'ep-1', target_id: 'user-1', relation: 'involves', weight: 1 },
    { id: 'e12', source_id: 'ep-1', target_id: 'user-2', relation: 'involves', weight: 1 },
    { id: 'e13', source_id: 'ep-2', target_id: 'project-1', relation: 'about', weight: 1 },
    { id: 'e14', source_id: 'ep-3', target_id: 'org-1', relation: 'organized_by', weight: 1 },
    { id: 'e15', source_id: 'cluster-1', target_id: 'user-1', relation: 'contains', weight: 0.5 },
    { id: 'e16', source_id: 'cluster-1', target_id: 'user-2', relation: 'contains', weight: 0.5 },
    { id: 'e17', source_id: 'cluster-2', target_id: 'tech-1', relation: 'contains', weight: 0.5 },
    { id: 'e18', source_id: 'cluster-2', target_id: 'tech-2', relation: 'contains', weight: 0.5 },
    { id: 'e19', source_id: 'cluster-3', target_id: 'project-1', relation: 'contains', weight: 0.5 },
    { id: 'e20', source_id: 'bridge-1', target_id: 'cluster-1', relation: 'connects', weight: 1 },
    { id: 'e21', source_id: 'bridge-1', target_id: 'cluster-2', relation: 'connects', weight: 1 },
    { id: 'e22', source_id: 'concept-1', target_id: 'tech-1', relation: 'applied_in', weight: 0.7 },
    { id: 'e23', source_id: 'org-1', target_id: 'project-1', relation: 'owns', weight: 1 },
  ]

  return { nodes, edges }
}

export function getNodeColor(kind: NodeKind): { bg: string; border: string; text: string } {
  const colors: Record<NodeKind, { bg: string; border: string; text: string }> = {
    entity: { bg: '#064e3b', border: '#10b981', text: '#6ee7b7' },
    fact: { bg: '#7c2d12', border: '#f97316', text: '#fdba74' },
    episode: { bg: '#1e3a5f', border: '#3b82f6', text: '#93c5fd' },
    cluster: { bg: '#4c1d95', border: '#a855f7', text: '#d8b4fe' },
    bridge: { bg: '#1e293b', border: '#64748b', text: '#94a3b8' },
  }
  return colors[kind] || colors.entity
}

export function filterGraphBySearch(data: GraphData, query: string): GraphData {
  if (!query.trim()) return data

  const lowerQuery = query.toLowerCase()
  const matchingNodeIds = new Set(
    data.nodes
      .filter(n => 
        n.label.toLowerCase().includes(lowerQuery) ||
        n.id.toLowerCase().includes(lowerQuery) ||
        n.kind.toLowerCase().includes(lowerQuery)
      )
      .map(n => n.id)
  )

  // Also include connected nodes
  const connectedIds = new Set<string>()
  data.edges.forEach(e => {
    if (matchingNodeIds.has(e.source_id)) connectedIds.add(e.target_id)
    if (matchingNodeIds.has(e.target_id)) connectedIds.add(e.source_id)
  })

  const allRelevantIds = new Set([...matchingNodeIds, ...connectedIds])
  
  return {
    nodes: data.nodes.filter(n => allRelevantIds.has(n.id)),
    edges: data.edges.filter(e => allRelevantIds.has(e.source_id) && allRelevantIds.has(e.target_id))
  }
}

export function getNeighbors(data: GraphData, nodeId: string): GraphData {
  const neighborIds = new Set<string>([nodeId])
  
  data.edges.forEach(e => {
    if (e.source_id === nodeId) neighborIds.add(e.target_id)
    if (e.target_id === nodeId) neighborIds.add(e.source_id)
  })

  return {
    nodes: data.nodes.filter(n => neighborIds.has(n.id)),
    edges: data.edges.filter(e => neighborIds.has(e.source_id) && neighborIds.has(e.target_id))
  }
}
