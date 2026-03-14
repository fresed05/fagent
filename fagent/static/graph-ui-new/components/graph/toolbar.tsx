"use client"

import {
  Maximize2,
  RefreshCw,
  Layers,
  Eye,
  EyeOff,
  Sparkles,
  Network,
  GitBranch,
  Circle,
  Target,
  Download,
  Settings2,
  Zap,
  TreePine,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Badge } from "@/components/ui/badge"

interface ToolbarProps {
  onFitView?: () => void
  onRelayout: () => void
  edgeOpacity: number
  onEdgeOpacityChange: (value: number) => void
  showLabels: boolean
  onToggleLabels: () => void
  nodeCount: number
  edgeCount: number
  layoutMode: "force" | "radial" | "hierarchical"
  onLayoutModeChange: (mode: "force" | "radial" | "hierarchical") => void
  nodeSize: number
  onNodeSizeChange: (size: number) => void
  performanceMode: boolean
  onPerformanceModeChange: (enabled: boolean) => void
}

export function Toolbar({
  onFitView,
  onRelayout,
  edgeOpacity,
  onEdgeOpacityChange,
  showLabels,
  onToggleLabels,
  nodeCount,
  edgeCount,
  layoutMode,
  onLayoutModeChange,
  nodeSize,
  onNodeSizeChange,
  performanceMode,
  onPerformanceModeChange,
}: ToolbarProps) {
  const isLargeGraph = nodeCount > 200 || edgeCount > 500

  return (
    <div className="absolute top-4 left-4 z-10 flex items-center gap-2 flex-wrap">
      {/* Stats badge */}
      <div className="flex items-center gap-2 px-3 py-2 bg-card/90 backdrop-blur-md rounded-xl border border-border/50 text-xs shadow-lg">
        <Sparkles className="w-3.5 h-3.5 text-primary" />
        <span className="font-medium">{nodeCount.toLocaleString()}</span>
        <span className="text-muted-foreground">nodes</span>
        <span className="text-border">|</span>
        <span className="font-medium">{edgeCount.toLocaleString()}</span>
        <span className="text-muted-foreground">edges</span>
        {isLargeGraph && (
          <Badge variant="secondary" className="ml-1 h-5 text-[10px] bg-amber-500/20 text-amber-300 border-amber-500/30">
            Large
          </Badge>
        )}
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
          title="Radial layout from selected node"
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
            title="Fit view (F)"
          >
            <Maximize2 className="h-4 w-4" />
          </Button>
        )}

        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={onRelayout}
          title="Re-layout graph (R)"
        >
          <RefreshCw className="h-4 w-4" />
        </Button>

        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={onToggleLabels}
          title={showLabels ? "Hide labels (L)" : "Show labels (L)"}
        >
          {showLabels ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
        </Button>

        {/* Settings popover */}
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="ghost" size="icon" className="h-8 w-8" title="Display settings">
              <Settings2 className="h-4 w-4" />
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-72" align="start">
            <div className="space-y-5">
              <div>
                <h4 className="font-medium text-sm mb-3">Display Settings</h4>
              </div>

              {/* Edge opacity */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="text-xs">Edge Visibility</Label>
                  <span className="text-xs text-muted-foreground font-mono">
                    {Math.round(edgeOpacity * 100)}%
                  </span>
                </div>
                <Slider
                  value={[edgeOpacity]}
                  onValueChange={([value]) => onEdgeOpacityChange(value)}
                  min={0}
                  max={1}
                  step={0.05}
                  className="w-full"
                />
              </div>

              {/* Node size */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="text-xs">Node Size</Label>
                  <span className="text-xs text-muted-foreground font-mono">
                    {Math.round(nodeSize * 100)}%
                  </span>
                </div>
                <Slider
                  value={[nodeSize]}
                  onValueChange={([value]) => onNodeSizeChange(value)}
                  min={0.5}
                  max={2}
                  step={0.1}
                  className="w-full"
                />
              </div>

              <Separator />

              {/* Performance mode */}
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label className="text-xs flex items-center gap-1.5">
                    <Zap className="w-3 h-3" />
                    Performance Mode
                  </Label>
                  <p className="text-[10px] text-muted-foreground">
                    Optimizes for large graphs
                  </p>
                </div>
                <Switch
                  checked={performanceMode}
                  onCheckedChange={onPerformanceModeChange}
                />
              </div>

              <Separator />

              {/* Keyboard shortcuts */}
              <div>
                <h5 className="text-xs font-medium mb-2">Keyboard Shortcuts</h5>
                <div className="grid grid-cols-2 gap-1 text-[10px] text-muted-foreground">
                  <span>Fit View</span><span className="font-mono text-right">F</span>
                  <span>Re-layout</span><span className="font-mono text-right">R</span>
                  <span>Toggle Labels</span><span className="font-mono text-right">L</span>
                  <span>Expand Node</span><span className="font-mono text-right">E</span>
                  <span>Delete</span><span className="font-mono text-right">Del</span>
                </div>
              </div>
            </div>
          </PopoverContent>
        </Popover>
      </div>

      {/* Performance mode indicator */}
      {performanceMode && (
        <div className="flex items-center gap-1.5 px-2 py-1 bg-amber-500/20 text-amber-300 rounded-lg border border-amber-500/30 text-[10px]">
          <Zap className="w-3 h-3" />
          Perf Mode
        </div>
      )}
    </div>
  )
}
