"use client"

import { useState, useMemo, useCallback, useRef } from "react"
import { Search, Filter, X, ChevronDown, SortAsc, SortDesc } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Toggle } from "@/components/ui/toggle"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { RawNode, NodeKind } from "@/lib/graph-types"
import { NODE_COLORS } from "@/lib/graph-types"

interface SearchPanelProps {
  nodes: RawNode[]
  onSelectNode: (nodeId: string) => void
  selectedNodeId?: string | null
}

const nodeKinds: NodeKind[] = ["entity", "fact", "episode", "cluster", "bridge"]

type SortOption = "priority" | "degree" | "name"

export function SearchPanel({ nodes, onSelectNode, selectedNodeId }: SearchPanelProps) {
  const [query, setQuery] = useState("")
  const [activeFilters, setActiveFilters] = useState<Set<NodeKind>>(new Set())
  const [showFilters, setShowFilters] = useState(false)
  const [sortBy, setSortBy] = useState<SortOption>("priority")
  const [sortAsc, setSortAsc] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  const filteredAndSortedNodes = useMemo(() => {
    let result = nodes

    // Filter by kind
    if (activeFilters.size > 0) {
      result = result.filter((node) => {
        const kind = (node.metadata?.kind || "entity") as NodeKind
        return activeFilters.has(kind)
      })
    }

    // Filter by search query
    if (query.trim()) {
      const q = query.toLowerCase()
      result = result.filter(
        (node) =>
          node.label.toLowerCase().includes(q) ||
          node.id.toLowerCase().includes(q) ||
          (node.metadata?.kind || "").toLowerCase().includes(q) ||
          (node.metadata?.topic as string || "").toLowerCase().includes(q)
      )
    }

    // Sort
    const sorted = [...result].sort((a, b) => {
      let comparison = 0
      switch (sortBy) {
        case "priority":
          comparison = (b.metadata?.priority_score || 0) - (a.metadata?.priority_score || 0)
          break
        case "degree":
          comparison = (b.degree || 0) - (a.degree || 0)
          break
        case "name":
          comparison = a.label.localeCompare(b.label)
          break
      }
      return sortAsc ? -comparison : comparison
    })

    return sorted
  }, [nodes, query, activeFilters, sortBy, sortAsc])

  const toggleFilter = useCallback((kind: NodeKind) => {
    setActiveFilters((prev) => {
      const next = new Set(prev)
      if (next.has(kind)) {
        next.delete(kind)
      } else {
        next.add(kind)
      }
      return next
    })
  }, [])

  // Get counts by kind
  const kindCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    nodes.forEach(node => {
      const kind = (node.metadata?.kind || "entity") as string
      counts[kind] = (counts[kind] || 0) + 1
    })
    return counts
  }, [nodes])

  // Virtualized rendering - only show visible items
  const visibleNodes = useMemo(() => {
    // Show max 200 items for performance
    return filteredAndSortedNodes.slice(0, 200)
  }, [filteredAndSortedNodes])

  return (
    <div className="h-full flex flex-col bg-card/50 backdrop-blur-sm overflow-hidden">
      {/* Header */}
      <div className="p-3 border-b border-border/30">
        <h2 className="text-sm font-semibold mb-3">Graph Explorer</h2>
        
        {/* Search input */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="Search nodes..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-9 pr-9 bg-background/50 h-9"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Filter and sort controls */}
        <div className="flex items-center justify-between mt-3">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs gap-1.5"
            onClick={() => setShowFilters(!showFilters)}
          >
            <Filter className="w-3.5 h-3.5" />
            Filters
            {activeFilters.size > 0 && (
              <Badge variant="secondary" className="h-4 px-1 text-[10px]">
                {activeFilters.size}
              </Badge>
            )}
          </Button>

          <div className="flex items-center gap-1">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="h-7 text-xs gap-1">
                  Sort: {sortBy}
                  <ChevronDown className="w-3 h-3" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => setSortBy("priority")}>
                  Priority
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setSortBy("degree")}>
                  Connections
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setSortBy("name")}>
                  Name
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => setSortAsc(!sortAsc)}
            >
              {sortAsc ? <SortAsc className="w-3.5 h-3.5" /> : <SortDesc className="w-3.5 h-3.5" />}
            </Button>
          </div>
        </div>

        {/* Filter toggles */}
        {showFilters && (
          <div className="flex flex-wrap gap-1.5 mt-3 pt-3 border-t border-border/30">
            {nodeKinds.map((kind) => {
              const colors = NODE_COLORS[kind] || NODE_COLORS.entity
              const isActive = activeFilters.has(kind)
              const count = kindCounts[kind] || 0
              return (
                <Toggle
                  key={kind}
                  pressed={isActive}
                  onPressedChange={() => toggleFilter(kind)}
                  size="sm"
                  className="h-7 text-[10px] capitalize gap-1.5 px-2"
                  style={{
                    background: isActive ? `${colors.glow}` : undefined,
                    borderColor: isActive ? colors.border : undefined,
                  }}
                >
                  <div
                    className="w-2 h-2 rounded-full"
                    style={{ background: colors.bg }}
                  />
                  {kind}
                  <span className="text-muted-foreground ml-0.5">({count})</span>
                </Toggle>
              )
            })}
            {activeFilters.size > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-[10px] px-2"
                onClick={() => setActiveFilters(new Set())}
              >
                Clear all
              </Button>
            )}
          </div>
        )}
      </div>

      {/* Results count */}
      <div className="px-3 py-2 text-[10px] text-muted-foreground border-b border-border/30 bg-secondary/20">
        Showing {visibleNodes.length} of {filteredAndSortedNodes.length} nodes
        {filteredAndSortedNodes.length > 200 && (
          <span className="ml-1">(limited for performance)</span>
        )}
      </div>

      {/* Results — flex-1 + overflow-hidden on parent makes ScrollArea scrollable */}
      <div className="flex-1 overflow-hidden">
      <ScrollArea className="h-full" ref={scrollRef}>
        <div className="p-2 space-y-0.5">
          {visibleNodes.map((node) => {
            const kind = (node.metadata?.kind || "entity") as NodeKind
            const colors = NODE_COLORS[kind] || NODE_COLORS.entity
            const isSelected = selectedNodeId === node.id

            return (
              <button
                key={node.id}
                onClick={() => onSelectNode(node.id)}
                className={`
                  w-full flex items-center gap-3 px-3 py-2 rounded-lg
                  text-left transition-all duration-150
                  ${isSelected
                    ? "bg-primary/15 ring-1 ring-primary/40"
                    : "hover:bg-secondary/50"
                  }
                `}
              >
                <div
                  className="w-2.5 h-2.5 rounded-full shrink-0 transition-shadow"
                  style={{
                    background: colors.bg,
                    boxShadow: isSelected ? `0 0 10px ${colors.glow}` : `0 0 4px ${colors.glow}`,
                  }}
                />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{node.label}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-[10px] text-muted-foreground capitalize">{kind}</span>
                    {node.degree !== undefined && node.degree > 0 && (
                      <span className="text-[10px] text-muted-foreground/70">
                        {node.degree} conn
                      </span>
                    )}
                    {node.metadata?.priority_score !== undefined && (
                      <span className="text-[10px] text-primary/60">
                        p{node.metadata.priority_score}
                      </span>
                    )}
                  </div>
                </div>
              </button>
            )
          })}

          {visibleNodes.length === 0 && (
            <div className="text-center py-12 text-muted-foreground">
              <Search className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p className="text-sm">No nodes match your search</p>
            </div>
          )}
        </div>
      </ScrollArea>
      </div>
    </div>
  )
}
