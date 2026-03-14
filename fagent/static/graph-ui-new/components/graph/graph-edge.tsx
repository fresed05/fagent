"use client"

import { memo, useMemo } from "react"
import { BaseEdge, getBezierPath, getSmoothStepPath, type EdgeProps } from "@xyflow/react"
import type { GraphEdgeData } from "@/lib/graph-types"

interface ExtendedEdgeData extends GraphEdgeData {
  isHighlighted?: boolean
  lodLevel?: number
  bundleOffset?: number
}

const GraphEdgeComponent = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
  style,
}: EdgeProps & { data?: ExtendedEdgeData }) => {
  const weight = data?.weight || 1
  const isHighlighted = data?.isHighlighted ?? false
  const isBundled = data?.isBundled ?? false
  const lodLevel = data?.lodLevel ?? 0
  const bundleOffset = data?.bundleOffset ?? 0

  // Calculate curvature based on bundling
  const curvature = isBundled ? 0.4 + bundleOffset * 0.05 : 0.25

  // Use different path types for performance
  const [edgePath] = useMemo(() => {
    if (lodLevel >= 2) {
      // Simple straight line for very zoomed out
      return [`M ${sourceX} ${sourceY} L ${targetX} ${targetY}`]
    }
    
    return getBezierPath({
      sourceX,
      sourceY,
      sourcePosition,
      targetX,
      targetY,
      targetPosition,
      curvature,
    })
  }, [sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, curvature, lodLevel])

  // Calculate visual properties
  const baseOpacity = style?.opacity ?? (0.15 + Math.min(0.5, weight * 0.15))
  const strokeWidth = Math.max(0.5, Math.min(3, weight * 1.2))
  
  const opacity = useMemo(() => {
    if (selected || isHighlighted) return 1
    if (lodLevel >= 2) return 0.1
    if (lodLevel >= 1) return baseOpacity * 0.6
    return baseOpacity
  }, [selected, isHighlighted, lodLevel, baseOpacity])

  const strokeColor = useMemo(() => {
    if (selected || isHighlighted) return "#60a5fa"
    if (isBundled) return "rgba(120, 140, 180, 0.6)"
    return `rgba(148, 163, 184, ${opacity})`
  }, [selected, isHighlighted, isBundled, opacity])

  // Skip rendering for very low opacity edges when zoomed out
  if (opacity < 0.05 && !selected && !isHighlighted) {
    return null
  }

  return (
    <>
      {/* Main edge */}
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke: strokeColor,
          strokeWidth: selected || isHighlighted ? strokeWidth + 1 : strokeWidth,
          strokeDasharray: data?.isAggregate ? "4 4" : undefined,
          strokeLinecap: "round",
          transition: "stroke 0.15s, stroke-width 0.15s, opacity 0.15s",
          opacity: opacity,
        }}
      />
      
      {/* Glow effect for highlighted/selected edges */}
      {(selected || isHighlighted) && (
        <BaseEdge
          id={`${id}-glow`}
          path={edgePath}
          style={{
            stroke: "#60a5fa",
            strokeWidth: strokeWidth + 6,
            filter: "blur(6px)",
            opacity: 0.4,
            strokeLinecap: "round",
          }}
        />
      )}

      {/* Arrow marker for directed edges (only at high zoom) */}
      {lodLevel === 0 && (selected || isHighlighted) && (
        <defs>
          <marker
            id={`arrow-${id}`}
            viewBox="0 0 10 10"
            refX="8"
            refY="5"
            markerWidth="4"
            markerHeight="4"
            orient="auto-start-reverse"
          >
            <path
              d="M 0 0 L 10 5 L 0 10 z"
              fill="#60a5fa"
              opacity={0.8}
            />
          </marker>
        </defs>
      )}
    </>
  )
}

export const GraphEdge = memo(GraphEdgeComponent)
