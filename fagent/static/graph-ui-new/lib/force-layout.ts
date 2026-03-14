import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  forceX,
  forceY,
  forceRadial,
  type Simulation,
  type SimulationNodeDatum,
  type SimulationLinkDatum,
} from "d3-force"
import type { GraphNode, GraphEdge } from "./graph-types"

interface ForceNode extends SimulationNodeDatum {
  id: string
  priority: number
  degree: number
  isCluster: boolean
  depth?: number
  group?: number
}

interface ForceLink extends SimulationLinkDatum<ForceNode> {
  source: string | ForceNode
  target: string | ForceNode
  weight: number
}

export interface LayoutOptions {
  width: number
  height: number
  centerStrength?: number
  chargeStrength?: number
  linkDistance?: number
  collideRadius?: number
  iterations?: number
  layoutMode?: "force" | "radial" | "hierarchical"
}

const defaultOptions: Required<LayoutOptions> = {
  width: 1200,
  height: 800,
  centerStrength: 0.05,
  chargeStrength: -300,
  linkDistance: 80,
  collideRadius: 30,
  iterations: 150,
  layoutMode: "force",
}

// Optimized layout with worker-friendly design
export function calculateForceLayout(
  nodes: GraphNode[],
  edges: GraphEdge[],
  options: Partial<LayoutOptions> = {}
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const opts = { ...defaultOptions, ...options }

  if (nodes.length === 0) return { nodes, edges }

  // Adaptive parameters based on graph size
  const nodeCount = nodes.length
  const edgeCount = edges.length
  const density = edgeCount / Math.max(1, nodeCount * (nodeCount - 1) / 2)
  
  // Reduce iterations for large graphs
  const adaptiveIterations = Math.min(opts.iterations, Math.max(50, 300 - nodeCount / 2))
  
  // Stronger repulsion for dense graphs
  const adaptiveCharge = opts.chargeStrength * (1 + density * 2)

  // Create force simulation nodes with initial positions
  const angleStep = (2 * Math.PI) / nodeCount
  const forceNodes: ForceNode[] = nodes.map((node, i) => {
    // Initial spiral layout for better convergence
    const angle = i * angleStep
    const radius = 50 + (i / nodeCount) * Math.min(opts.width, opts.height) * 0.4
    
    return {
      id: node.id,
      priority: node.data.priority || 5,
      degree: node.data.degree || 1,
      isCluster: node.data.isCluster || false,
      depth: node.data.depth,
      x: opts.width / 2 + Math.cos(angle) * radius,
      y: opts.height / 2 + Math.sin(angle) * radius,
    }
  })

  // Create force links
  const nodeIds = new Set(nodes.map((n) => n.id))
  const forceLinks: ForceLink[] = edges
    .filter((edge) => nodeIds.has(edge.source as string) && nodeIds.has(edge.target as string))
    .map((edge) => ({
      source: edge.source as string,
      target: edge.target as string,
      weight: edge.data?.weight || 1,
    }))

  // Build adjacency for group detection
  const adjacency = new Map<string, Set<string>>()
  forceLinks.forEach(link => {
    const s = typeof link.source === "string" ? link.source : link.source.id
    const t = typeof link.target === "string" ? link.target : link.target.id
    if (!adjacency.has(s)) adjacency.set(s, new Set())
    if (!adjacency.has(t)) adjacency.set(t, new Set())
    adjacency.get(s)!.add(t)
    adjacency.get(t)!.add(s)
  })

  // Simple community detection for grouping
  const visited = new Set<string>()
  let groupId = 0
  forceNodes.forEach(node => {
    if (!visited.has(node.id)) {
      const queue = [node.id]
      while (queue.length > 0) {
        const current = queue.shift()!
        if (visited.has(current)) continue
        visited.add(current)
        
        const fNode = forceNodes.find(n => n.id === current)
        if (fNode) fNode.group = groupId
        
        adjacency.get(current)?.forEach(neighbor => {
          if (!visited.has(neighbor)) queue.push(neighbor)
        })
      }
      groupId++
    }
  })

  // Create simulation with adaptive forces
  const simulation: Simulation<ForceNode, ForceLink> = forceSimulation(forceNodes)
    .force(
      "link",
      forceLink<ForceNode, ForceLink>(forceLinks)
        .id((d) => d.id)
        .distance((d) => {
          const baseDistance = opts.linkDistance
          const weightFactor = 1 / Math.max(0.3, d.weight)
          return baseDistance * weightFactor
        })
        .strength((d) => {
          const baseStrength = 0.3
          return Math.min(1, baseStrength + d.weight * 0.2)
        })
    )
    .force(
      "charge",
      forceManyBody<ForceNode>()
        .strength((d) => {
          const base = adaptiveCharge
          const degreeFactor = 1 + Math.log10(1 + d.degree) * 0.3
          const clusterFactor = d.isCluster ? 2 : 1
          const priorityFactor = 1 + d.priority * 0.02
          return base * degreeFactor * clusterFactor * priorityFactor
        })
        .distanceMax(400)
        .theta(0.9) // Performance optimization
    )
    .force("center", forceCenter(opts.width / 2, opts.height / 2).strength(opts.centerStrength))
    .force(
      "collide",
      forceCollide<ForceNode>()
        .radius((d) => {
          const base = opts.collideRadius
          const degreeFactor = 1 + Math.log10(1 + d.degree) * 0.2
          const clusterFactor = d.isCluster ? 1.5 : 1
          return base * degreeFactor * clusterFactor
        })
        .strength(0.7)
        .iterations(1) // Performance optimization
    )
    // Gentle centering forces by group
    .force(
      "x",
      forceX<ForceNode>((d) => {
        if (d.group !== undefined) {
          const groupOffset = ((d.group % 5) - 2) * opts.width * 0.15
          return opts.width / 2 + groupOffset
        }
        return opts.width / 2
      }).strength(0.02)
    )
    .force(
      "y",
      forceY<ForceNode>((d) => {
        if (d.group !== undefined) {
          const groupOffset = (Math.floor(d.group / 5) - 1) * opts.height * 0.15
          return opts.height / 2 + groupOffset
        }
        return opts.height / 2
      }).strength(0.02)
    )
    .stop()

  // Run simulation
  for (let i = 0; i < adaptiveIterations; i++) {
    simulation.tick()
  }

  // Map positions back to nodes
  const positionMap = new Map(forceNodes.map((n) => [n.id, { x: n.x || 0, y: n.y || 0 }]))

  const layoutedNodes = nodes.map((node) => {
    const pos = positionMap.get(node.id) || { x: 0, y: 0 }
    return {
      ...node,
      position: { x: pos.x, y: pos.y },
    }
  })

  return { nodes: layoutedNodes, edges }
}

// Radial layout for hierarchical display
export function calculateRadialLayout(
  nodes: GraphNode[],
  edges: GraphEdge[],
  centerNodeId?: string,
  options: Partial<LayoutOptions> = {}
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const opts = { ...defaultOptions, ...options }
  
  if (nodes.length === 0) return { nodes, edges }

  // Find center node (highest degree or specified)
  const centerNode = centerNodeId 
    ? nodes.find(n => n.id === centerNodeId) 
    : nodes.reduce((a, b) => (a.data.degree || 0) > (b.data.degree || 0) ? a : b)
  
  if (!centerNode) return calculateForceLayout(nodes, edges, options)

  // Build adjacency
  const adjacency = new Map<string, Set<string>>()
  edges.forEach(edge => {
    const s = edge.source as string
    const t = edge.target as string
    if (!adjacency.has(s)) adjacency.set(s, new Set())
    if (!adjacency.has(t)) adjacency.set(t, new Set())
    adjacency.get(s)!.add(t)
    adjacency.get(t)!.add(s)
  })

  // BFS to assign depths
  const depths = new Map<string, number>([[centerNode.id, 0]])
  const queue = [centerNode.id]
  
  while (queue.length > 0) {
    const current = queue.shift()!
    const currentDepth = depths.get(current)!
    
    adjacency.get(current)?.forEach(neighbor => {
      if (!depths.has(neighbor)) {
        depths.set(neighbor, currentDepth + 1)
        queue.push(neighbor)
      }
    })
  }

  // Assign positions by depth rings
  const maxDepth = Math.max(...Array.from(depths.values()))
  const depthGroups = new Map<number, string[]>()
  
  depths.forEach((depth, nodeId) => {
    if (!depthGroups.has(depth)) depthGroups.set(depth, [])
    depthGroups.get(depth)!.push(nodeId)
  })

  const positionMap = new Map<string, { x: number; y: number }>()
  const cx = opts.width / 2
  const cy = opts.height / 2
  const maxRadius = Math.min(opts.width, opts.height) * 0.45

  depthGroups.forEach((nodeIds, depth) => {
    const radius = depth === 0 ? 0 : (depth / maxDepth) * maxRadius
    const angleStep = (2 * Math.PI) / nodeIds.length
    
    nodeIds.forEach((nodeId, i) => {
      const angle = i * angleStep - Math.PI / 2
      positionMap.set(nodeId, {
        x: cx + Math.cos(angle) * radius,
        y: cy + Math.sin(angle) * radius,
      })
    })
  })

  // Handle unconnected nodes
  nodes.forEach(node => {
    if (!positionMap.has(node.id)) {
      positionMap.set(node.id, {
        x: cx + (Math.random() - 0.5) * opts.width * 0.8,
        y: cy + (Math.random() - 0.5) * opts.height * 0.8,
      })
    }
  })

  const layoutedNodes = nodes.map((node) => ({
    ...node,
    position: positionMap.get(node.id) || { x: cx, y: cy },
    data: { ...node.data, depth: depths.get(node.id) ?? -1 },
  }))

  return { nodes: layoutedNodes, edges }
}

// Edge bundling algorithm
export function bundleEdges(
  edges: GraphEdge[],
  nodes: GraphNode[]
): GraphEdge[] {
  if (edges.length < 20) return edges
  
  const nodePositions = new Map(nodes.map(n => [n.id, n.position]))
  
  // Group edges by their general direction
  const bundleGroups = new Map<string, GraphEdge[]>()
  
  edges.forEach(edge => {
    const sourcePos = nodePositions.get(edge.source as string)
    const targetPos = nodePositions.get(edge.target as string)
    
    if (!sourcePos || !targetPos) return
    
    // Quantize direction to create bundles
    const dx = targetPos.x - sourcePos.x
    const dy = targetPos.y - sourcePos.y
    const angle = Math.atan2(dy, dx)
    const quantizedAngle = Math.round(angle / (Math.PI / 8)) * (Math.PI / 8)
    
    // Create bundle key based on direction and region
    const regionX = Math.round((sourcePos.x + targetPos.x) / 200)
    const regionY = Math.round((sourcePos.y + targetPos.y) / 200)
    const bundleKey = `${quantizedAngle.toFixed(2)}_${regionX}_${regionY}`
    
    if (!bundleGroups.has(bundleKey)) bundleGroups.set(bundleKey, [])
    bundleGroups.get(bundleKey)!.push(edge)
  })

  // Return edges with bundle information
  return edges.map(edge => {
    const sourcePos = nodePositions.get(edge.source as string)
    const targetPos = nodePositions.get(edge.target as string)
    
    if (!sourcePos || !targetPos) return edge
    
    const dx = targetPos.x - sourcePos.x
    const dy = targetPos.y - sourcePos.y
    const angle = Math.atan2(dy, dx)
    const quantizedAngle = Math.round(angle / (Math.PI / 8)) * (Math.PI / 8)
    const regionX = Math.round((sourcePos.x + targetPos.x) / 200)
    const regionY = Math.round((sourcePos.y + targetPos.y) / 200)
    const bundleKey = `${quantizedAngle.toFixed(2)}_${regionX}_${regionY}`
    
    const bundleSize = bundleGroups.get(bundleKey)?.length || 1
    
    return {
      ...edge,
      data: {
        ...edge.data,
        isBundled: bundleSize > 3,
        bundleId: bundleKey,
      },
    }
  })
}
