"use client"

import { memo, useCallback } from "react"
import { Handle, Position, type NodeProps } from "@xyflow/react"
import type { GraphNodeData, NodeKind } from "@/lib/graph-types"
import { NODE_COLORS, LOD_THRESHOLDS } from "@/lib/graph-types"

interface ExtendedNodeData extends GraphNodeData {
  lodLevel?: number
  isPinned?: boolean
  isHighlighted?: boolean
  onContextMenu?: (e: React.MouseEvent) => void
}

const GraphNodeComponent = ({ 
  id,
  data, 
  selected,
}: NodeProps & { data: ExtendedNodeData }) => {
  const colors = NODE_COLORS[data.kind] || NODE_COLORS.entity
  const lodLevel = data.lodLevel ?? 0
  const isPinned = data.isPinned ?? false
  const isHighlighted = data.isHighlighted ?? false
  
  // Size based on priority and degree
  const baseSize = 24
  const priorityBonus = (data.priority || 5) * 2
  const degreeBonus = Math.min(20, Math.log10(1 + (data.degree || 0)) * 10)
  const size = Math.max(24, baseSize + priorityBonus + degreeBonus)

  const isCluster = data.isCluster
  const displayLabel = data.label.length > 25 ? data.label.slice(0, 23) + "…" : data.label

  // LOD Level 2: Dot only (very zoomed out)
  if (lodLevel >= 2) {
    return (
      <>
        <Handle type="target" position={Position.Top} className="!opacity-0 !w-1 !h-1" />
        <div
          className="rounded-full"
          style={{
            width: Math.max(4, size * 0.3),
            height: Math.max(4, size * 0.3),
            background: colors.bg,
            opacity: isHighlighted ? 1 : 0.6,
          }}
        />
        <Handle type="source" position={Position.Bottom} className="!opacity-0 !w-1 !h-1" />
      </>
    )
  }

  // LOD Level 1: Simplified (medium zoom)
  if (lodLevel >= 1) {
    return (
      <>
        <Handle type="target" position={Position.Top} className="!opacity-0 !w-1 !h-1" />
        <div
          className={`relative flex items-center justify-center ${isCluster ? "rounded-lg" : "rounded-full"}`}
          style={{
            width: size * 0.7,
            height: size * 0.7,
            background: colors.bg,
            border: `1.5px solid ${colors.border}`,
            boxShadow: selected || isHighlighted ? `0 0 12px ${colors.glow}` : "none",
            opacity: isHighlighted ? 1 : 0.8,
          }}
        >
          {isCluster && data.clusterSize && (
            <span className="text-white font-bold text-[8px]">{data.clusterSize}</span>
          )}
        </div>
        <Handle type="source" position={Position.Bottom} className="!opacity-0 !w-1 !h-1" />
      </>
    )
  }

  // LOD Level 0: Full detail
  return (
    <>
      <Handle type="target" position={Position.Top} className="!opacity-0 !w-2 !h-2" />
      <div
        className="relative flex items-center justify-center transition-transform duration-150"
        style={{
          width: size,
          height: size,
          transform: selected ? "scale(1.1)" : "scale(1)",
        }}
      >
        {/* Glow effect */}
        <div
          className="absolute inset-0 rounded-full blur-xl transition-all duration-300"
          style={{
            background: colors.glow,
            opacity: selected || isHighlighted ? 0.9 : 0.25,
            transform: selected ? "scale(2)" : "scale(1.2)",
          }}
        />

        {/* Pin indicator */}
        {isPinned && (
          <div className="absolute -top-1 -right-1 w-3 h-3 bg-primary rounded-full flex items-center justify-center z-20">
            <div className="w-1.5 h-1.5 bg-white rounded-full" />
          </div>
        )}

        {/* Main node */}
        <div
          className={`
            relative z-10 flex items-center justify-center
            transition-all duration-200
            ${isCluster ? "rounded-xl" : "rounded-full"}
            ${selected ? "ring-2 ring-white/80 ring-offset-2 ring-offset-transparent" : ""}
          `}
          style={{
            width: size,
            height: size,
            background: `radial-gradient(circle at 30% 30%, ${colors.border}, ${colors.bg})`,
            boxShadow: `0 4px 20px ${colors.glow}, inset 0 2px 4px rgba(255,255,255,0.15)`,
            border: `2px solid ${colors.border}`,
          }}
        >
          {isCluster && data.clusterSize && (
            <span className="text-white font-bold text-xs">{data.clusterSize}</span>
          )}
        </div>

        {/* Label - show for high priority or selected */}
        {(data.priority >= 6 || selected || isHighlighted) && (
          <div
            className={`
              absolute top-full mt-2 px-2 py-1
              text-xs font-medium text-white/95
              bg-black/70 backdrop-blur-md rounded-md
              whitespace-nowrap pointer-events-none
              transition-all duration-200 shadow-lg
              ${selected || isHighlighted ? "opacity-100 scale-100" : "opacity-85 scale-95"}
            `}
            style={{
              maxWidth: 180,
              textOverflow: "ellipsis",
              overflow: "hidden",
            }}
          >
            {displayLabel}
            {isCluster && (
              <span className="ml-1.5 text-[10px] text-white/60">
                ({data.clusterSize})
              </span>
            )}
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!opacity-0 !w-2 !h-2" />
    </>
  )
}

export const GraphNode = memo(GraphNodeComponent)
