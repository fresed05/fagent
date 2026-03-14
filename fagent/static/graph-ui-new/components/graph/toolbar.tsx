"use client"

import {
  Maximize2,
  RefreshCw,
  Eye,
  EyeOff,
  Sparkles,
  Network,
  GitBranch,
  Target,
  TreePine,
} from "lucide-react"
import { Button } from "@/components/ui/button"

interface ToolbarProps {
  onFitView?: () => void
  onRelayout: () => void
  showLabels: boolean
  onToggleLabels: () => void
  nodeCount: number
  edgeCount: number
  layoutMode: "force" | "radial" | "hierarchical"
  onLayoutModeChange: (mode: "force" | "radial" | "hierarchical") => void
}

export function Toolbar({
  onFitView,
  onRelayout,
  showLabels,
  onToggleLabels,
  nodeCount,
  edgeCount,
  layoutMode,
  onLayoutModeChange,
}: ToolbarProps) {
  return (
    <div className="absolute top-4 left-4 z-10 flex items-center gap-2 flex-wrap">
      {/* Stats badge */}
      <div className="flex items-center gap-2 px-3 py-2 bg-card/90 backdrop-blur-md rounded-xl border border-border/50 text-xs shadow-lg">
        <Sparkles className="w-3.5 h-3.5 text-primary" />
        <span className="font-medium" suppressHydrationWarning>{nodeCount.toLocaleString()}</span>
        <span className="text-muted-foreground">nodes</span>
        <span className="text-border">|</span>
        <span className="font-medium" suppressHydrationWarning>{edgeCount.toLocaleString()}</span>
        <span className="text-muted-foreground">edges</span>
      </div>

      {/* Layout selector */}
      <div className="flex items-center gap-1 p-1 bg-card/90 backdrop-blur-md rounded-xl border border-border/50 shadow-lg">
        <Button
          variant={layoutMode === "force" ? "secondary" : "ghost"}
          size="sm"
          className="h-8 px-3 text-xs gap-1.5"
          onClick={() => onLayoutModeChange("force")}
          title="Force-directed layout"
        >
          <Network className="h-3.5 w-3.5" />
          Force
        </Button>
        <Button
          variant={layoutMode === "radial" ? "secondary" : "ghost"}
          size="sm"
          className="h-8 px-3 text-xs gap-1.5"
          onClick={() => onLayoutModeChange("radial")}
          title="Radial layout"
        >
          <Target className="h-3.5 w-3.5" />
          Radial
        </Button>
        <Button
          variant={layoutMode === "hierarchical" ? "secondary" : "ghost"}
          size="sm"
          className="h-8 px-3 text-xs gap-1.5"
          onClick={() => onLayoutModeChange("hierarchical")}
          title="Hierarchical tree layout"
        >
          <TreePine className="h-3.5 w-3.5" />
          Tree
        </Button>
      </div>

      {/* View controls */}
      <div className="flex items-center gap-1 p-1 bg-card/90 backdrop-blur-md rounded-xl border border-border/50 shadow-lg">
        {onFitView && (
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={onFitView}
            title="Fit view"
          >
            <Maximize2 className="h-4 w-4" />
          </Button>
        )}

        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={onRelayout}
          title="Re-layout graph"
        >
          <RefreshCw className="h-4 w-4" />
        </Button>

        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={onToggleLabels}
          title={showLabels ? "Hide labels" : "Show labels"}
        >
          {showLabels ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
        </Button>
      </div>
    </div>
  )
}
