"use client"

import { useState } from "react"
import { 
  X, 
  Network, 
  Tag, 
  GitBranch, 
  ChevronRight, 
  Edit3, 
  Trash2, 
  Link2,
  Plus,
  Search,
  ArrowUpRight,
  MoreHorizontal,
  Eye,
  EyeOff,
  Lock,
  Unlock,
  Copy,
} from "lucide-react"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu"
import type { NodeDetails, RawNode, RawEdge, NodeKind } from "@/lib/graph-types"
import { NODE_COLORS } from "@/lib/graph-types"

interface DetailsPanelProps {
  details: NodeDetails | null
  onClose: () => void
  onSelectNode: (nodeId: string) => void
  onEditNode?: (nodeId: string) => void
  onDeleteNode?: (nodeId: string) => void
  onHideNode?: (nodeId: string) => void
  onPinNode?: (nodeId: string) => void
}

const kindLabels: Record<NodeKind, string> = {
  entity: "Entity",
  fact: "Fact",
  episode: "Episode",
  cluster: "Cluster",
  bridge: "Bridge",
}

export function DetailsPanel({ 
  details, 
  onClose, 
  onSelectNode,
  onEditNode,
  onDeleteNode,
  onHideNode,
  onPinNode,
}: DetailsPanelProps) {
  const [neighborSearch, setNeighborSearch] = useState("")
  const [activeTab, setActiveTab] = useState("connections")

  if (!details) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground p-6 bg-card/30">
        <div className="text-center">
          <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-secondary/50 flex items-center justify-center">
            <Network className="w-8 h-8 opacity-50" />
          </div>
          <p className="text-sm font-medium">No Node Selected</p>
          <p className="text-xs text-muted-foreground mt-1">
            Click on a node or right-click for options
          </p>
        </div>
      </div>
    )
  }

  const kind = details.kind || "entity"
  const colors = NODE_COLORS[kind]

  // Filter neighbors by search
  const filteredNeighbors = details.neighbors?.filter(n => 
    neighborSearch === "" || 
    n.label.toLowerCase().includes(neighborSearch.toLowerCase())
  ) || []

  // Group edges by relation type
  const edgesByRelation = (details.edges || []).reduce((acc, edge) => {
    const rel = edge.relation
    if (!acc[rel]) acc[rel] = []
    acc[rel].push(edge)
    return acc
  }, {} as Record<string, RawEdge[]>)

  const handleCopyId = () => {
    navigator.clipboard.writeText(details.selected_id)
  }

  return (
    <div className="h-full flex flex-col bg-card/50 backdrop-blur-sm">
      {/* Header */}
      <div className="p-4 border-b border-border/50 bg-card/30">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <div
                className="w-4 h-4 rounded-full shrink-0 shadow-lg"
                style={{ 
                  background: colors.bg, 
                  boxShadow: `0 0 12px ${colors.glow}` 
                }}
              />
              <Badge 
                variant="outline" 
                className="text-[10px] uppercase tracking-wider font-semibold"
                style={{ borderColor: colors.border, color: colors.bg }}
              >
                {kindLabels[kind]}
              </Badge>
              {details.metadata?.confidence && (
                <Badge variant="secondary" className="text-[10px]">
                  {Math.round((details.metadata.confidence as number) * 100)}% conf
                </Badge>
              )}
            </div>
            <h3 className="font-semibold text-lg leading-tight line-clamp-2">{details.title}</h3>
            <p className="text-xs text-muted-foreground mt-1 font-mono">
              ID: {details.selected_id}
            </p>
          </div>
          
          <div className="flex items-center gap-1">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-8 w-8">
                  <MoreHorizontal className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={handleCopyId}>
                  <Copy className="h-4 w-4 mr-2" />
                  Copy ID
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onEditNode?.(details.selected_id)}>
                  <Edit3 className="h-4 w-4 mr-2" />
                  Edit Node
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onPinNode?.(details.selected_id)}>
                  <Lock className="h-4 w-4 mr-2" />
                  Pin Position
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => onHideNode?.(details.selected_id)}>
                  <EyeOff className="h-4 w-4 mr-2" />
                  Hide Node
                </DropdownMenuItem>
                <DropdownMenuItem 
                  onClick={() => onDeleteNode?.(details.selected_id)}
                  className="text-destructive focus:text-destructive"
                >
                  <Trash2 className="h-4 w-4 mr-2" />
                  Delete Node
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Quick stats */}
        <div className="flex items-center gap-4 mt-3 pt-3 border-t border-border/30">
          <div className="flex items-center gap-1.5 text-xs">
            <Network className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="font-medium">{details.neighbors?.length || 0}</span>
            <span className="text-muted-foreground">connections</span>
          </div>
          <div className="flex items-center gap-1.5 text-xs">
            <GitBranch className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="font-medium">{details.edges?.length || 0}</span>
            <span className="text-muted-foreground">edges</span>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col min-h-0">
        <TabsList className="mx-4 mt-3 bg-secondary/50">
          <TabsTrigger value="connections" className="text-xs flex-1">
            Connections
          </TabsTrigger>
          <TabsTrigger value="relations" className="text-xs flex-1">
            Relations
          </TabsTrigger>
          <TabsTrigger value="metadata" className="text-xs flex-1">
            Metadata
          </TabsTrigger>
        </TabsList>

        <ScrollArea className="flex-1">
          <TabsContent value="connections" className="p-4 pt-2 mt-0">
            {/* Search neighbors */}
            <div className="relative mb-3">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
              <Input
                placeholder="Search connections..."
                value={neighborSearch}
                onChange={(e) => setNeighborSearch(e.target.value)}
                className="h-8 pl-8 text-xs bg-background/50"
              />
            </div>

            {/* Neighbors list */}
            <div className="space-y-1">
              {filteredNeighbors.map((neighbor: RawNode) => {
                const neighborKind = (neighbor.metadata?.kind || "entity") as NodeKind
                const neighborColors = NODE_COLORS[neighborKind]
                const edge = details.edges?.find(e => 
                  e.source_id === neighbor.id || e.target_id === neighbor.id
                )
                
                return (
                  <button
                    key={neighbor.id}
                    onClick={() => onSelectNode(neighbor.id)}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg bg-secondary/20 hover:bg-secondary/40 transition-all duration-150 text-left group"
                  >
                    <div
                      className="w-3 h-3 rounded-full shrink-0 transition-shadow"
                      style={{
                        background: neighborColors.bg,
                        boxShadow: `0 0 8px ${neighborColors.glow}`,
                      }}
                    />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate group-hover:text-primary transition-colors">
                        {neighbor.label}
                      </p>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-muted-foreground capitalize">
                          {neighborKind}
                        </span>
                        {edge && (
                          <span className="text-[10px] text-primary/70 font-mono">
                            {edge.relation}
                          </span>
                        )}
                      </div>
                    </div>
                    <ArrowUpRight className="w-4 h-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                  </button>
                )
              })}

              {filteredNeighbors.length === 0 && (
                <div className="text-center py-8 text-muted-foreground text-xs">
                  {neighborSearch ? "No matching connections" : "No connections"}
                </div>
              )}
            </div>
          </TabsContent>

          <TabsContent value="relations" className="p-4 pt-2 mt-0">
            <div className="space-y-4">
              {Object.entries(edgesByRelation).map(([relation, edges]) => (
                <div key={relation}>
                  <div className="flex items-center gap-2 mb-2">
                    <Badge variant="outline" className="text-[10px] font-mono">
                      {relation}
                    </Badge>
                    <span className="text-[10px] text-muted-foreground">
                      {edges.length} edge{edges.length !== 1 ? "s" : ""}
                    </span>
                  </div>
                  <div className="space-y-1 pl-2">
                    {edges.slice(0, 5).map((edge, idx) => {
                      const otherId = edge.source_id === details.selected_id 
                        ? edge.target_id 
                        : edge.source_id
                      const otherNode = details.neighbors?.find(n => n.id === otherId)
                      const direction = edge.source_id === details.selected_id ? "to" : "from"
                      
                      return (
                        <button
                          key={idx}
                          onClick={() => onSelectNode(otherId)}
                          className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs hover:bg-secondary/30 transition-colors text-left"
                        >
                          <span className="text-muted-foreground">{direction}</span>
                          <span className="font-medium truncate flex-1">
                            {otherNode?.label || otherId}
                          </span>
                          {edge.weight && edge.weight !== 1 && (
                            <span className="text-[10px] text-muted-foreground">
                              w:{edge.weight.toFixed(1)}
                            </span>
                          )}
                        </button>
                      )
                    })}
                    {edges.length > 5 && (
                      <p className="text-[10px] text-muted-foreground pl-2">
                        +{edges.length - 5} more
                      </p>
                    )}
                  </div>
                </div>
              ))}

              {Object.keys(edgesByRelation).length === 0 && (
                <div className="text-center py-8 text-muted-foreground text-xs">
                  No relationships
                </div>
              )}
            </div>
          </TabsContent>

          <TabsContent value="metadata" className="p-4 pt-2 mt-0">
            {/* Summary */}
            {details.summary && (
              <div className="mb-4">
                <h4 className="text-xs uppercase tracking-wider text-muted-foreground mb-2 flex items-center gap-2">
                  <Tag className="w-3.5 h-3.5" />
                  Summary
                </h4>
                <p className="text-sm text-foreground/80 leading-relaxed">{details.summary}</p>
              </div>
            )}

            {/* Raw metadata */}
            {details.metadata && Object.keys(details.metadata).length > 0 && (
              <div>
                <h4 className="text-xs uppercase tracking-wider text-muted-foreground mb-2">
                  Properties
                </h4>
                <div className="bg-secondary/30 rounded-lg p-3 font-mono text-[11px] overflow-auto max-h-64">
                  <pre className="text-foreground/70 whitespace-pre-wrap">
                    {JSON.stringify(details.metadata, null, 2)}
                  </pre>
                </div>
              </div>
            )}
          </TabsContent>
        </ScrollArea>
      </Tabs>
    </div>
  )
}
