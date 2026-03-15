"use client"

import { useEffect, useRef } from "react"
import { Expand, EyeOff, MousePointer2, Layers } from "lucide-react"

export interface NodeContextMenuProps {
  x: number
  y: number
  nodeId: string
  nodeLabel: string
  isCluster: boolean
  clusterSize?: number
  onSelect: () => void
  onExpand?: () => void
  onHide: () => void
  onClose: () => void
}

export function NodeContextMenu({
  x,
  y,
  nodeId,
  nodeLabel,
  isCluster,
  clusterSize,
  onSelect,
  onExpand,
  onHide,
  onClose,
}: NodeContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)

  // Close on outside click or Escape
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("mousedown", handleClick)
    document.addEventListener("keydown", handleKey)
    return () => {
      document.removeEventListener("mousedown", handleClick)
      document.removeEventListener("keydown", handleKey)
    }
  }, [onClose])

  // Adjust position so menu stays within viewport
  const menuWidth = 220
  const menuX = typeof window !== "undefined" && x + menuWidth > window.innerWidth ? x - menuWidth : x
  const menuY = y

  return (
    <div
      ref={menuRef}
      className="fixed z-50 min-w-[220px] py-1.5 bg-card/95 backdrop-blur-lg border border-border/60 rounded-xl shadow-2xl"
      style={{ left: menuX, top: menuY }}
    >
      {/* Header */}
      <div className="px-3 py-2 border-b border-border/40">
        <div className="flex items-center gap-2">
          <div
            className="w-2.5 h-2.5 rounded-sm shrink-0"
            style={{
              background: isCluster ? "#a855f7" : "#10b981",
              boxShadow: `0 0 6px ${isCluster ? "rgba(168,85,247,0.5)" : "rgba(16,185,129,0.5)"}`,
            }}
          />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{nodeLabel}</p>
            <p className="text-[10px] text-muted-foreground capitalize">
              {isCluster ? `Cluster · ${clusterSize ?? "?"} members` : "Node"}
            </p>
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="py-1">
        <button
          onClick={() => { onSelect(); onClose() }}
          className="w-full flex items-center gap-2.5 px-3 py-2 text-sm hover:bg-secondary/60 transition-colors text-left"
        >
          <MousePointer2 className="w-4 h-4 text-muted-foreground" />
          Select node
        </button>

        {isCluster && onExpand && (
          <button
            onClick={() => { onExpand(); onClose() }}
            className="w-full flex items-center gap-2.5 px-3 py-2 text-sm hover:bg-secondary/60 transition-colors text-left text-primary"
          >
            <Expand className="w-4 h-4" />
            Expand cluster
          </button>
        )}

        <div className="my-1 border-t border-border/30" />

        <button
          onClick={() => { onHide(); onClose() }}
          className="w-full flex items-center gap-2.5 px-3 py-2 text-sm hover:bg-destructive/15 transition-colors text-left text-destructive"
        >
          <EyeOff className="w-4 h-4" />
          Hide node
        </button>
      </div>
    </div>
  )
}
