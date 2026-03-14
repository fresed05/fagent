"use client"

import { useCallback, useEffect, useMemo, useState, useRef } from "react"
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  useReactFlow,
  useViewport,
  type OnNodesChange,
  type OnEdgesChange,
  BackgroundVariant,
  type Viewport,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { GraphNode } from "./graph-node"
import { GraphEdge } from "./graph-edge"
import { ContextMenu } from "./context-menu"
import type { 
  GraphNode as GraphNodeType, 
  GraphEdge as GraphEdgeType, 
  RawNode, 
  RawEdge, 
  NodeKind,
  LOD_THRESHOLDS,
  PERFORMANCE_CONFIG,
} from "@/lib/graph-types"
import { NODE_COLORS } from "@/lib/graph-types"
import { calculateForceLayout, calculateRadialLayout, bundleEdges } from "@/lib/force-layout"

interface GraphCanvasProps {
  rawNodes: RawNode[]
  rawEdges: RawEdge[]
  selectedNodeId: string | null
  onSelectNode: (nodeId: string | null) => void
  layoutMode?: "force" | "radial" | "hierarchical"
  onExpandCluster?: (clusterId: string) => void
  onCollapseNodes?: (nodeIds: string[]) => void
  hiddenNodeIds?: Set<string>
}

const nodeTypes = { graphNode: GraphNode }
const edgeTypes = { graphEdge: GraphEdge }

// LOD thresholds
const LOD = {
  FULL_DETAIL: 0.5,
  SIMPLIFIED: 0.15,
  DOT_ONLY: 0.06,
}

// Performance config
const PERF = {
  MAX_VISIBLE_NODES: 600,
  MAX_VISIBLE_EDGES: 1500,
  VIEWPORT_PADDING: 200,
}

function transformNodes(rawNodes: RawNode[], width: number, height: number): GraphNodeType[] {
  return rawNodes.map((node, index) => ({
    id: node.id,
    type: "graphNode",
    position: {
      x: width / 2 + Math.cos(index * 0.3) * Math.min(width, height) * 0.35,
      y: height / 2 + Math.sin(index * 0.3) * Math.min(width, height) * 0.35,
    },
    data: {
      label: node.label,
      kind: (node.metadata?.kind || "entity") as NodeKind,
      priority: node.metadata?.priority_score || 5,
      confidence: node.metadata?.confidence,
      isCluster: node.metadata?.is_cluster,
      clusterSize: node.metadata?.cluster_size,
      metadata: node.metadata,
      degree: node.degree,
      childIds: node.metadata?.child_ids as string[] | undefined,
      parentId: node.metadata?.parent_id as string | undefined,
    },
  }))
}

function transformEdges(rawEdges: RawEdge[], nodeIds: Set<string>): GraphEdgeType[] {
  return rawEdges
    .filter((edge) => nodeIds.has(edge.source_id) && nodeIds.has(edge.target_id))
    .map((edge, index) => ({
      id: `edge-${index}-${edge.source_id}-${edge.target_id}`,
      source: edge.source_id,
      target: edge.target_id,
      type: "graphEdge",
      data: {
        relation: edge.relation,
        weight: edge.weight || 1,
        isAggregate: edge.metadata?.is_aggregate,
        memberCount: edge.metadata?.member_edge_count,
      },
    }))
}

export function GraphCanvas({
  rawNodes,
  rawEdges,
  selectedNodeId,
  onSelectNode,
  layoutMode = "force",
  onExpandCluster,
  onCollapseNodes,
  hiddenNodeIds = new Set(),
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [isLayouted, setIsLayouted] = useState(false)
  const [dimensions, setDimensions] = useState({ width: 1200, height: 800 })
  const [pinnedNodes, setPinnedNodes] = useState<Set<string>>(new Set())
  const { fitView, setCenter, getViewport, setViewport } = useReactFlow()
  const viewport = useViewport()

  // Context menu state
  const [contextMenu, setContextMenu] = useState<{
    x: number
    y: number
    node: GraphNodeType | null
    isOpen: boolean
  }>({ x: 0, y: 0, node: null, isOpen: false })

  // Filter hidden nodes
  const visibleRawNodes = useMemo(() => 
    rawNodes.filter(n => !hiddenNodeIds.has(n.id)),
    [rawNodes, hiddenNodeIds]
  )

  // Transform raw data to React Flow format
  const { initialNodes, initialEdges } = useMemo(() => {
    const nodes = transformNodes(visibleRawNodes, dimensions.width, dimensions.height)
    const nodeIds = new Set(visibleRawNodes.map((n) => n.id))
    const edges = transformEdges(rawEdges, nodeIds)
    return { initialNodes: nodes, initialEdges: edges }
  }, [visibleRawNodes, rawEdges, dimensions])

  const [nodes, setNodes, onNodesChange] = useNodesState<GraphNodeType>(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState<GraphEdgeType>(initialEdges)

  // Calculate LOD level based on zoom
  const lodLevel = useMemo(() => {
    const zoom = viewport.zoom
    if (zoom >= LOD.FULL_DETAIL) return 0
    if (zoom >= LOD.SIMPLIFIED) return 1
    return 2
  }, [viewport.zoom])

  // Update dimensions on resize
  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        setDimensions({
          width: containerRef.current.offsetWidth,
          height: containerRef.current.offsetHeight,
        })
      }
    }

    updateDimensions()
    const resizeObserver = new ResizeObserver(updateDimensions)
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current)
    }
    return () => resizeObserver.disconnect()
  }, [])

  // Apply layout on initial load or when data changes
  useEffect(() => {
    if (initialNodes.length === 0) return

    const layoutFn = layoutMode === "radial" ? calculateRadialLayout : calculateForceLayout
    
    const { nodes: layoutedNodes, edges: layoutedEdges } = layoutFn(
      initialNodes, 
      initialEdges, 
      layoutMode === "radial" ? selectedNodeId || undefined : undefined,
      {
        width: dimensions.width,
        height: dimensions.height,
        chargeStrength: -300 - initialNodes.length * 0.5,
        linkDistance: 60 + Math.max(0, 40 - initialNodes.length * 0.1),
        collideRadius: 25 + Math.max(0, 15 - initialNodes.length * 0.05),
        iterations: Math.max(80, 200 - initialNodes.length * 0.3),
      }
    )

    // Apply edge bundling
    const bundledEdges = bundleEdges(layoutedEdges, layoutedNodes)

    setNodes(layoutedNodes)
    setEdges(bundledEdges)
    setIsLayouted(true)

    // Fit view after layout
    setTimeout(() => {
      fitView({ padding: 0.15, duration: 400 })
    }, 50)
  }, [initialNodes.length, initialEdges.length, dimensions, layoutMode])

  // Center on selected node
  useEffect(() => {
    if (selectedNodeId && isLayouted) {
      const node = nodes.find((n) => n.id === selectedNodeId)
      if (node) {
        setCenter(node.position.x, node.position.y, { duration: 400, zoom: Math.max(0.6, viewport.zoom) })
      }
    }
  }, [selectedNodeId, isLayouted])

  // Handle node click
  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: GraphNodeType) => {
      onSelectNode(node.id)
    },
    [onSelectNode]
  )

  // Handle context menu
  const handleNodeContextMenu = useCallback(
    (event: React.MouseEvent, node: GraphNodeType) => {
      event.preventDefault()
      setContextMenu({
        x: event.clientX,
        y: event.clientY,
        node,
        isOpen: true,
      })
    },
    []
  )

  const handlePaneContextMenu = useCallback((event: React.MouseEvent) => {
    event.preventDefault()
    setContextMenu({
      x: event.clientX,
      y: event.clientY,
      node: null,
      isOpen: true,
    })
  }, [])

  const handleContextMenuClose = useCallback(() => {
    setContextMenu(prev => ({ ...prev, isOpen: false }))
  }, [])

  const handleContextMenuAction = useCallback(
    (action: string, nodeId: string) => {
      switch (action) {
        case "expand":
        case "expand-cluster":
          if (onExpandCluster) onExpandCluster(nodeId)
          break
        case "collapse":
          if (onCollapseNodes) {
            const node = nodes.find(n => n.id === nodeId)
            if (node) {
              // Get connected nodes
              const connectedIds = edges
                .filter(e => e.source === nodeId || e.target === nodeId)
                .map(e => e.source === nodeId ? e.target : e.source)
              onCollapseNodes([nodeId, ...connectedIds])
            }
          }
          break
        case "focus":
          const node = nodes.find(n => n.id === nodeId)
          if (node) {
            setCenter(node.position.x, node.position.y, { duration: 400, zoom: 1.2 })
          }
          break
        case "hide":
          // Would be handled by parent
          break
        case "pin":
          setPinnedNodes(prev => {
            const next = new Set(prev)
            if (next.has(nodeId)) next.delete(nodeId)
            else next.add(nodeId)
            return next
          })
          break
        case "copy":
          navigator.clipboard.writeText(nodeId)
          break
        case "isolate":
          // Focus on node's neighborhood
          onSelectNode(nodeId)
          break
        case "show-all":
          fitView({ padding: 0.15, duration: 400 })
          break
        case "reset-view":
          fitView({ padding: 0.15, duration: 400 })
          break
      }
    },
    [nodes, edges, onExpandCluster, onCollapseNodes, onSelectNode, setCenter, fitView]
  )

  const handlePaneClick = useCallback(() => {
    onSelectNode(null)
  }, [onSelectNode])

  // Update nodes with selection, LOD, and highlighting
  const processedNodes = useMemo(() => {
    // Get connected node IDs for highlighting
    const highlightedIds = new Set<string>()
    if (selectedNodeId) {
      highlightedIds.add(selectedNodeId)
      edges.forEach(edge => {
        if (edge.source === selectedNodeId) highlightedIds.add(edge.target)
        if (edge.target === selectedNodeId) highlightedIds.add(edge.source)
      })
    }

    return nodes.map((node) => ({
      ...node,
      selected: node.id === selectedNodeId,
      data: {
        ...node.data,
        lodLevel,
        isPinned: pinnedNodes.has(node.id),
        isHighlighted: highlightedIds.has(node.id),
      },
    }))
  }, [nodes, selectedNodeId, lodLevel, pinnedNodes, edges])

  // Process edges with visibility and highlighting
  const processedEdges = useMemo(() => {
    // Limit visible edges for performance
    let visibleEdges = edges

    // At low zoom, reduce edge count
    if (lodLevel >= 2 && edges.length > PERF.MAX_VISIBLE_EDGES) {
      // Keep only higher weight edges
      visibleEdges = [...edges]
        .sort((a, b) => (b.data?.weight || 0) - (a.data?.weight || 0))
        .slice(0, PERF.MAX_VISIBLE_EDGES * 0.3)
    } else if (lodLevel >= 1 && edges.length > PERF.MAX_VISIBLE_EDGES) {
      visibleEdges = [...edges]
        .sort((a, b) => (b.data?.weight || 0) - (a.data?.weight || 0))
        .slice(0, PERF.MAX_VISIBLE_EDGES * 0.6)
    }

    return visibleEdges.map((edge) => {
      const isConnected = selectedNodeId && 
        (edge.source === selectedNodeId || edge.target === selectedNodeId)

      return {
        ...edge,
        selected: isConnected,
        data: {
          ...edge.data,
          lodLevel,
          isHighlighted: isConnected,
        },
        style: {
          ...edge.style,
          opacity: selectedNodeId
            ? (isConnected ? 1 : 0.08)
            : undefined,
        },
      }
    })
  }, [edges, selectedNodeId, lodLevel])

  // MiniMap node color
  const minimapNodeColor = useCallback((node: GraphNodeType) => {
    const colors = NODE_COLORS[node.data.kind]
    return colors?.bg || "#6b7280"
  }, [])

  return (
    <div ref={containerRef} className="w-full h-full relative">
      <ReactFlow
        nodes={processedNodes}
        edges={processedEdges}
        onNodesChange={onNodesChange as OnNodesChange}
        onEdgesChange={onEdgesChange as OnEdgesChange}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={handleNodeClick}
        onNodeContextMenu={handleNodeContextMenu}
        onPaneClick={handlePaneClick}
        onPaneContextMenu={handlePaneContextMenu}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.02}
        maxZoom={2.5}
        defaultEdgeOptions={{ type: "graphEdge" }}
        proOptions={{ hideAttribution: true }}
        className="bg-transparent"
        nodesDraggable={lodLevel < 2}
        nodesConnectable={false}
        elementsSelectable={true}
        panOnScroll={true}
        zoomOnScroll={true}
        preventScrolling={true}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={lodLevel >= 2 ? 48 : 24}
          size={lodLevel >= 2 ? 0.5 : 1}
          color="rgba(148, 163, 184, 0.12)"
        />
        <Controls
          showZoom={true}
          showFitView={true}
          showInteractive={false}
          className="!bg-card/90 !backdrop-blur-md !border-border/50 !rounded-xl !shadow-xl"
        />
        <MiniMap
          nodeColor={minimapNodeColor}
          maskColor="rgba(0, 0, 0, 0.85)"
          className="!bg-card/90 !backdrop-blur-md !border-border/50 !rounded-xl"
          style={{ height: 120, width: 180 }}
          pannable
          zoomable
        />
      </ReactFlow>

      {/* Context Menu */}
      <ContextMenu
        x={contextMenu.x}
        y={contextMenu.y}
        node={contextMenu.node}
        isOpen={contextMenu.isOpen}
        onClose={handleContextMenuClose}
        onAction={handleContextMenuAction}
      />

      {/* Performance indicator */}
      {(nodes.length > 300 || edges.length > 800) && (
        <div className="absolute bottom-4 left-4 px-3 py-1.5 bg-card/80 backdrop-blur-sm rounded-lg border border-border/50 text-xs text-muted-foreground">
          LOD: {lodLevel === 0 ? "Full" : lodLevel === 1 ? "Medium" : "Low"} | 
          Zoom: {(viewport.zoom * 100).toFixed(0)}%
        </div>
      )}
    </div>
  )
}
