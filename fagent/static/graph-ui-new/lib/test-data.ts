import type { RawNode, RawEdge, NodeKind } from "./graph-types"

// Generate a massive knowledge graph for stress testing (10,000+ connections possible)
export function generateTestData(options: {
  nodeCount?: number
  connectivityFactor?: number
} = {}): { nodes: RawNode[]; edges: RawEdge[] } {
  const { nodeCount = 200, connectivityFactor = 0.08 } = options
  
  const nodes: RawNode[] = []
  const edges: RawEdge[] = []

  // Category definitions with proper hierarchy
  const categories = [
    { prefix: "tech", label: "Technology", kind: "entity" as NodeKind, count: Math.floor(nodeCount * 0.25) },
    { prefix: "person", label: "Person", kind: "entity" as NodeKind, count: Math.floor(nodeCount * 0.15) },
    { prefix: "company", label: "Company", kind: "entity" as NodeKind, count: Math.floor(nodeCount * 0.1) },
    { prefix: "concept", label: "Concept", kind: "fact" as NodeKind, count: Math.floor(nodeCount * 0.2) },
    { prefix: "event", label: "Event", kind: "episode" as NodeKind, count: Math.floor(nodeCount * 0.15) },
    { prefix: "project", label: "Project", kind: "fact" as NodeKind, count: Math.floor(nodeCount * 0.15) },
  ]

  // Topic clusters for realistic grouping
  const topics = [
    "AI", "Web", "Mobile", "Cloud", "Security", "Data", "ML", "DevOps", 
    "Blockchain", "IoT", "AR/VR", "Quantum", "Robotics", "Biotech"
  ]

  const techTerms = [
    "Framework", "Library", "Platform", "API", "SDK", "Protocol", "Algorithm",
    "Architecture", "System", "Engine", "Runtime", "Compiler", "Database"
  ]

  const actions = [
    "created", "improved", "uses", "extends", "relates_to", "part_of",
    "inspired", "competes_with", "collaborates", "implements", "integrates"
  ]

  // Generate nodes by category
  let nodeIndex = 0
  const nodesByCategory: Record<string, RawNode[]> = {}

  categories.forEach(({ prefix, label, kind, count }) => {
    nodesByCategory[prefix] = []
    for (let i = 0; i < count; i++) {
      const topic = topics[Math.floor(Math.random() * topics.length)]
      const term = techTerms[Math.floor(Math.random() * techTerms.length)]
      const nodeLabel = `${topic} ${term} ${i + 1}`
      const priority = Math.floor(Math.random() * 8) + 2 // 2-10
      
      const node: RawNode = {
        id: `${prefix}_${nodeIndex}`,
        label: nodeLabel,
        metadata: {
          kind,
          priority_score: priority,
          confidence: 0.5 + Math.random() * 0.5,
          category: label,
          topic,
        },
        degree: 0,
      }
      nodes.push(node)
      nodesByCategory[prefix].push(node)
      nodeIndex++
    }
  })

  // Create hierarchical clusters
  const clusterCount = Math.floor(nodeCount / 30)
  for (let i = 0; i < clusterCount; i++) {
    const topic = topics[i % topics.length]
    const cluster: RawNode = {
      id: `cluster_${i}`,
      label: `${topic} Domain`,
      metadata: {
        kind: "cluster",
        priority_score: 8,
        is_cluster: true,
        cluster_size: Math.floor(Math.random() * 20) + 5,
        topic,
      },
      degree: 0,
    }
    nodes.push(cluster)
    
    // Connect cluster to related nodes
    const relatedNodes = nodes.filter(n => 
      n.metadata?.topic === topic && 
      n.id !== cluster.id && 
      !n.metadata?.is_cluster
    )
    
    relatedNodes.slice(0, 15).forEach(n => {
      edges.push({
        source_id: cluster.id,
        target_id: n.id,
        relation: "contains",
        weight: 0.5,
        metadata: { is_aggregate: true },
      })
    })
  }

  // Generate edges with smart connectivity
  const nodeIds = nodes.map(n => n.id)
  const nonClusterNodes = nodes.filter(n => !n.metadata?.is_cluster)
  
  // Within-category connections (stronger)
  Object.values(nodesByCategory).forEach(categoryNodes => {
    const n = categoryNodes.length
    const edgeCount = Math.floor(n * n * connectivityFactor * 0.5)
    
    for (let i = 0; i < edgeCount; i++) {
      const source = categoryNodes[Math.floor(Math.random() * n)]
      const target = categoryNodes[Math.floor(Math.random() * n)]
      
      if (source.id !== target.id && !edges.some(e => 
        (e.source_id === source.id && e.target_id === target.id) ||
        (e.source_id === target.id && e.target_id === source.id)
      )) {
        const action = actions[Math.floor(Math.random() * actions.length)]
        edges.push({
          source_id: source.id,
          target_id: target.id,
          relation: action,
          weight: 0.5 + Math.random() * 1,
        })
      }
    }
  })

  // Cross-category connections (weaker, based on shared topics)
  const crossEdgeCount = Math.floor(nodeCount * connectivityFactor * 2)
  for (let i = 0; i < crossEdgeCount; i++) {
    const source = nonClusterNodes[Math.floor(Math.random() * nonClusterNodes.length)]
    const sameTopic = nonClusterNodes.filter(n => 
      n.id !== source.id && 
      n.metadata?.topic === source.metadata?.topic
    )
    
    if (sameTopic.length > 0) {
      const target = sameTopic[Math.floor(Math.random() * sameTopic.length)]
      
      if (!edges.some(e => 
        (e.source_id === source.id && e.target_id === target.id) ||
        (e.source_id === target.id && e.target_id === source.id)
      )) {
        const action = actions[Math.floor(Math.random() * actions.length)]
        edges.push({
          source_id: source.id,
          target_id: target.id,
          relation: action,
          weight: 0.3 + Math.random() * 0.5,
        })
      }
    }
  }

  // Random long-range connections for "small world" effect
  const longRangeCount = Math.floor(nodeCount * 0.02)
  for (let i = 0; i < longRangeCount; i++) {
    const source = nonClusterNodes[Math.floor(Math.random() * nonClusterNodes.length)]
    const target = nonClusterNodes[Math.floor(Math.random() * nonClusterNodes.length)]
    
    if (source.id !== target.id && !edges.some(e => 
      (e.source_id === source.id && e.target_id === target.id) ||
      (e.source_id === target.id && e.target_id === source.id)
    )) {
      edges.push({
        source_id: source.id,
        target_id: target.id,
        relation: "related_to",
        weight: 0.2 + Math.random() * 0.3,
      })
    }
  }

  // Calculate degree for each node
  const degreeMap = new Map<string, number>()
  edges.forEach(e => {
    degreeMap.set(e.source_id, (degreeMap.get(e.source_id) || 0) + 1)
    degreeMap.set(e.target_id, (degreeMap.get(e.target_id) || 0) + 1)
  })
  
  nodes.forEach(n => {
    n.degree = degreeMap.get(n.id) || 0
  })

  return { nodes, edges }
}

export function getNodeDetails(nodeId: string, data: { nodes: RawNode[]; edges: RawEdge[] }) {
  const node = data.nodes.find((n) => n.id === nodeId)
  if (!node) return null

  const connectedEdges = data.edges.filter((e) => e.source_id === nodeId || e.target_id === nodeId)
  const neighborIds = new Set(
    connectedEdges.map((e) => (e.source_id === nodeId ? e.target_id : e.source_id))
  )
  const neighbors = data.nodes.filter((n) => neighborIds.has(n.id))

  return {
    selected_id: nodeId,
    title: node.label,
    kind: node.metadata?.kind || "entity",
    summary: `${node.label} is a ${node.metadata?.kind || "node"} with ${connectedEdges.length} connections.`,
    metadata: node.metadata || {},
    neighbors,
    edges: connectedEdges,
  }
}

// Utility to filter nodes by depth from a root
export function getNodesAtDepth(
  rootId: string, 
  edges: RawEdge[], 
  maxDepth: number
): Set<string> {
  const visited = new Set<string>([rootId])
  let frontier = new Set<string>([rootId])
  
  for (let depth = 0; depth < maxDepth; depth++) {
    const nextFrontier = new Set<string>()
    
    edges.forEach(e => {
      if (frontier.has(e.source_id) && !visited.has(e.target_id)) {
        nextFrontier.add(e.target_id)
        visited.add(e.target_id)
      }
      if (frontier.has(e.target_id) && !visited.has(e.source_id)) {
        nextFrontier.add(e.source_id)
        visited.add(e.source_id)
      }
    })
    
    frontier = nextFrontier
  }
  
  return visited
}
