"use client"

import type { NodeKind } from "@/lib/graph-types"
import { NODE_COLORS } from "@/lib/graph-types"

const legendItems: { kind: NodeKind; label: string }[] = [
  { kind: "entity", label: "Entity" },
  { kind: "fact", label: "Fact" },
  { kind: "episode", label: "Episode" },
  { kind: "cluster", label: "Cluster" },
  { kind: "bridge", label: "Bridge" },
]

export function Legend() {
  return (
    <div className="absolute bottom-4 left-4 z-10 flex items-center gap-3 px-3 py-2 bg-card/90 backdrop-blur-md rounded-xl border border-border/50 shadow-lg">
      {legendItems.map(({ kind, label }) => {
        const colors = NODE_COLORS[kind]
        return (
          <div key={kind} className="flex items-center gap-1.5">
            <div
              className="w-2.5 h-2.5 rounded-full"
              style={{
                background: colors.bg,
                boxShadow: `0 0 6px ${colors.glow}`,
              }}
            />
            <span className="text-[10px] text-muted-foreground font-medium">
              {label}
            </span>
          </div>
        )
      })}
    </div>
  )
}
