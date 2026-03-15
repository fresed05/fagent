"use client"

import { RefreshCw, Eye, EyeOff, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"

interface ToolbarProps {
  onReload: () => void
  showLabels: boolean
  onToggleLabels: () => void
  nodeCount: number
  edgeCount: number
  loading?: boolean
}

export function Toolbar({
  onReload,
  showLabels,
  onToggleLabels,
  nodeCount,
  edgeCount,
  loading = false,
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

      {/* Controls */}
      <div className="flex items-center gap-1 p-1 bg-card/90 backdrop-blur-md rounded-xl border border-border/50 shadow-lg">
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={onReload}
          disabled={loading}
          title="Reload graph data from server"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </Button>

        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={onToggleLabels}
          title={showLabels ? "Hide node labels" : "Show node labels"}
        >
          {showLabels ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
        </Button>
      </div>
    </div>
  )
}
