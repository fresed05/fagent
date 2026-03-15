"use client"

import { useState, useCallback, useEffect } from "react"
import dynamic from "next/dynamic"
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable"

const ForceGraphCanvas = dynamic(() => import("./force-graph-canvas").then(mod => ({ default: mod.ForceGraphCanvas })), {
  ssr: false,
})
import { SearchPanel } from "./search-panel"
import { DetailsPanel } from "./details-panel"
import { Toolbar } from "./toolbar"
import { Legend } from "./legend"
import { NodeContextMenu } from "./node-context-menu"
import type { RawNode, RawEdge, NodeDetails } from "@/lib/graph-types"
import type { NodeRightClickInfo } from "./force-graph-canvas"
import {
  fetchGraphOverview,
  fetchGraphDetails,
  fetchGraphFocus,
  type GraphMode,
} from "@/lib/api-client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Database, RefreshCw, AlertCircle, Loader2 } from "lucide-react"

// Header component
function Header({
  nodeCount,
  edgeCount,
  loading,
}: {
  nodeCount: number
  edgeCount: number
  loading: boolean
}) {
  return (
    <header className="flex items-center justify-between px-6 py-3 border-b border-border/30 bg-card/50 backdrop-blur-md">
      <div className="flex items-center gap-4">
        <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-primary via-primary/80 to-accent text-primary-foreground font-bold text-sm shadow-lg">
          GA
        </div>
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Graph Atlas</h1>
          <p className="text-xs text-muted-foreground">
            Interactive knowledge graph visualization
          </p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Database className="w-3.5 h-3.5" />
          <span suppressHydrationWarning>{nodeCount.toLocaleString()} nodes</span>
          <span className="text-border">|</span>
          <span suppressHydrationWarning>{edgeCount.toLocaleString()} edges</span>
        </div>
        {loading && (
          <span className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-full bg-muted/50 text-muted-foreground border border-border/40">
            <Loader2 className="w-3 h-3 animate-spin" />
            Loading…
          </span>
        )}
      </div>
    </header>
  )
}

// Graph query / mode settings panel
function GraphSettings({
  query,
  onQueryChange,
  session,
  onSessionChange,
  mode,
  onModeChange,
  onReload,
  loading,
}: {
  query: string
  onQueryChange: (v: string) => void
  session: string
  onSessionChange: (v: string) => void
  mode: GraphMode
  onModeChange: (m: GraphMode) => void
  onReload: () => void
  loading: boolean
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 gap-2 text-xs">
          <Database className="w-3.5 h-3.5" />
          Graph Settings
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80" align="end">
        <div className="space-y-4">
          <div>
            <h4 className="font-medium text-sm mb-1">Graph Source</h4>
            <p className="text-xs text-muted-foreground">
              Filter and reload the graph from memory
            </p>
          </div>

          <div className="space-y-2">
            <Label className="text-xs">Search Query</Label>
            <Input
              value={query}
              onChange={e => onQueryChange(e.target.value)}
              placeholder="Search entities, facts…"
              className="h-8 text-xs"
            />
          </div>

          <div className="space-y-2">
            <Label className="text-xs">Session Filter</Label>
            <Input
              value={session}
              onChange={e => onSessionChange(e.target.value)}
              placeholder="Optional session key"
              className="h-8 text-xs"
            />
          </div>

          <div className="space-y-2">
            <Label className="text-xs">Map Mode</Label>
            <Select value={mode} onValueChange={v => onModeChange(v as GraphMode)}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="global-clustered">Atlas (clustered)</SelectItem>
                <SelectItem value="global-raw">Raw (all nodes)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <Button
            onClick={onReload}
            disabled={loading}
            className="w-full"
            size="sm"
          >
            {loading ? (
              <Loader2 className="w-3.5 h-3.5 mr-2 animate-spin" />
            ) : (
              <RefreshCw className="w-3.5 h-3.5 mr-2" />
            )}
            Reload Graph
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}

// Error banner
function ErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="absolute top-16 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-4 py-3 rounded-lg bg-destructive/10 border border-destructive/30 text-sm text-destructive shadow-lg">
      <AlertCircle className="w-4 h-4 shrink-0" />
      <span>{message}</span>
      <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={onRetry}>
        Retry
      </Button>
    </div>
  )
}

// Inner component
function GraphAtlasInner() {
  // Graph source settings
  const [query, setQuery] = useState("")
  const [session, setSession] = useState("")
  const [mode, setMode] = useState<GraphMode>("global-clustered")

  // Data state
  const [currentNodes, setCurrentNodes] = useState<RawNode[]>([])
  const [currentEdges, setCurrentEdges] = useState<RawEdge[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // UI state
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [selectedDetails, setSelectedDetails] = useState<NodeDetails | null>(null)
  const [showLabels, setShowLabels] = useState(true)
  const [layoutKey, setLayoutKey] = useState(0)
  const [hiddenNodeIds, setHiddenNodeIds] = useState<Set<string>>(new Set())
  const [contextMenu, setContextMenu] = useState<NodeRightClickInfo | null>(null)

  // Read URL params on mount
  useEffect(() => {
    if (typeof window === "undefined") return
    const params = new URLSearchParams(window.location.search)
    const q = params.get("query") || ""
    const s = params.get("session") || ""
    const m = (params.get("mode") || "global-clustered") as GraphMode
    setQuery(q)
    setSession(s)
    setMode(m)
  }, [])

  // Load graph from API
  const loadGraph = useCallback(async (
    q: string,
    s: string,
    m: GraphMode,
  ) => {
    setLoading(true)
    setError(null)
    try {
      const payload = await fetchGraphOverview({ query: q, session: s, mode: m })
      setCurrentNodes((payload.nodes ?? []) as RawNode[])
      setCurrentEdges((payload.edges ?? []) as RawEdge[])
      setHiddenNodeIds(new Set())
      setSelectedNodeId(null)
      setSelectedDetails(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load graph")
    } finally {
      setLoading(false)
    }
  }, [])

  // Initial load (triggered after URL params are set)
  const [initialLoaded, setInitialLoaded] = useState(false)
  useEffect(() => {
    if (initialLoaded) return
    // Wait for URL params to be applied (next tick)
    const timer = setTimeout(() => {
      setInitialLoaded(true)
    }, 50)
    return () => clearTimeout(timer)
  }, [initialLoaded])

  useEffect(() => {
    if (!initialLoaded) return
    loadGraph(query, session, mode)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialLoaded])

  // Handlers
  const handleSelectNode = useCallback(async (nodeId: string | null) => {
    setSelectedNodeId(nodeId)
    if (!nodeId) {
      setSelectedDetails(null)
      return
    }
    try {
      const details = await fetchGraphDetails(nodeId, { query, session })
      setSelectedDetails(details)
    } catch {
      // silently ignore — details panel will show empty state
      setSelectedDetails(null)
    }
  }, [query, session])

  const handleExpandCluster = useCallback(async (clusterId: string) => {
    try {
      const focusPayload = await fetchGraphFocus(clusterId, { query, session })
      if (focusPayload.nodes.length > 0) {
        // Merge cluster members into the current graph
        const existingIds = new Set(currentNodes.map(n => n.id))
        const newNodes = focusPayload.nodes.filter(n => !existingIds.has(n.id))
        const existingEdgeKeys = new Set(
          currentEdges.map(e => `${e.source_id}|${e.relation}|${e.target_id}`)
        )
        const newEdges = focusPayload.edges.filter(
          e => !existingEdgeKeys.has(`${e.source_id}|${e.relation}|${e.target_id}`)
        )
        setCurrentNodes(prev => [...prev, ...newNodes])
        setCurrentEdges(prev => [...prev, ...newEdges])
      }
    } catch {
      // silently ignore
    }
  }, [currentNodes, currentEdges, query, session])

  const handleCollapseNodes = useCallback((nodeIds: string[]) => {
    setHiddenNodeIds(prev => new Set([...prev, ...nodeIds]))
  }, [])

  const handleHideNode = useCallback((nodeId: string) => {
    setHiddenNodeIds(prev => new Set([...prev, nodeId]))
    if (selectedNodeId === nodeId) {
      setSelectedNodeId(null)
      setSelectedDetails(null)
    }
  }, [selectedNodeId])

  const handleRelayout = useCallback(() => {
    setLayoutKey(k => k + 1)
  }, [])

  const handleCloseDetails = useCallback(() => {
    setSelectedNodeId(null)
    setSelectedDetails(null)
  }, [])

  const handleReload = useCallback(() => {
    loadGraph(query, session, mode)
  }, [loadGraph, query, session, mode])

  const handleModeChange = useCallback((newMode: GraphMode) => {
    setMode(newMode)
    loadGraph(query, session, newMode)
  }, [loadGraph, query, session])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return
      }
      switch (e.key.toLowerCase()) {
        case "r":
          handleRelayout()
          break
        case "l":
          setShowLabels(prev => !prev)
          break
        case "escape":
          setSelectedNodeId(null)
          setSelectedDetails(null)
          break
        case "delete":
        case "backspace":
          if (selectedNodeId) {
            handleHideNode(selectedNodeId)
          }
          break
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [handleRelayout, selectedNodeId, handleHideNode])

  return (
    <div className="h-screen flex flex-col bg-gradient-to-br from-background via-background to-secondary/10">
      <Header
        nodeCount={currentNodes.length}
        edgeCount={currentEdges.length}
        loading={loading}
      />

      {error && <ErrorBanner message={error} onRetry={handleReload} />}

      <div className="flex-1 flex relative overflow-hidden">
        <ResizablePanelGroup direction="horizontal">
          {/* Left sidebar - Search */}
          <ResizablePanel defaultSize={18} minSize={12} maxSize={28}>
            <div className="h-full flex flex-col">
              <SearchPanel
                nodes={currentNodes}
                onSelectNode={handleSelectNode}
                selectedNodeId={selectedNodeId}
              />
            </div>
          </ResizablePanel>

          <ResizableHandle withHandle className="bg-border/30 hover:bg-border/50 transition-colors" />

          {/* Main graph canvas */}
          <ResizablePanel defaultSize={57}>
            <div className="relative h-full">
              <Toolbar
                onReload={handleReload}
                showLabels={showLabels}
                onToggleLabels={() => setShowLabels(prev => !prev)}
                nodeCount={currentNodes.length - hiddenNodeIds.size}
                edgeCount={currentEdges.length}
                loading={loading}
              />

              {/* Loading overlay */}
              {loading && currentNodes.length === 0 && (
                <div className="absolute inset-0 flex items-center justify-center z-20 bg-background/60 backdrop-blur-sm">
                  <div className="flex flex-col items-center gap-3">
                    <Loader2 className="w-8 h-8 animate-spin text-primary" />
                    <p className="text-sm text-muted-foreground">Loading graph…</p>
                  </div>
                </div>
              )}

              <ForceGraphCanvas
                key={String(layoutKey)}
                rawNodes={currentNodes}
                rawEdges={currentEdges}
                selectedNodeId={selectedNodeId}
                showLabels={showLabels}
                onSelectNode={handleSelectNode}
                onNodeRightClick={setContextMenu}
                onExpandCluster={handleExpandCluster}
                onCollapseNodes={handleCollapseNodes}
                hiddenNodeIds={hiddenNodeIds}
              />

              <Legend />

              {/* Graph settings */}
              <div className="absolute bottom-4 right-4 z-10">
                <GraphSettings
                  query={query}
                  onQueryChange={setQuery}
                  session={session}
                  onSessionChange={setSession}
                  mode={mode}
                  onModeChange={handleModeChange}
                  onReload={handleReload}
                  loading={loading}
                />
              </div>

              {/* Context menu */}
              {contextMenu && (
                <NodeContextMenu
                  x={contextMenu.screenX}
                  y={contextMenu.screenY}
                  nodeId={contextMenu.nodeId}
                  nodeLabel={contextMenu.nodeLabel}
                  isCluster={contextMenu.isCluster}
                  clusterSize={contextMenu.clusterSize}
                  onSelect={() => handleSelectNode(contextMenu.nodeId)}
                  onExpand={contextMenu.isCluster ? () => handleExpandCluster(contextMenu.nodeId) : undefined}
                  onHide={() => handleHideNode(contextMenu.nodeId)}
                  onClose={() => setContextMenu(null)}
                />
              )}
            </div>
          </ResizablePanel>

          <ResizableHandle withHandle className="bg-border/30 hover:bg-border/50 transition-colors" />

          {/* Right sidebar - Details */}
          <ResizablePanel defaultSize={25} minSize={18} maxSize={38}>
            <DetailsPanel
              details={selectedDetails}
              onClose={handleCloseDetails}
              onSelectNode={handleSelectNode}
              onExpandCluster={handleExpandCluster}
              onHideNode={handleHideNode}
            />
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
    </div>
  )
}

// Main export
export function GraphAtlas() {
  return <GraphAtlasInner />
}
