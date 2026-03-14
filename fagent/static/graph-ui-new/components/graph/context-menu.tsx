"use client"

import { useCallback, useEffect, useRef } from "react"
import {
  Expand,
  Shrink,
  Focus,
  Eye,
  EyeOff,
  Trash2,
  Link2,
  Unlink,
  Copy,
  Edit3,
  Lock,
  Unlock,
  Sparkles,
  GitBranch,
  Layers,
} from "lucide-react"
import type { GraphNode as GraphNodeType, NodeKind } from "@/lib/graph-types"
import { NODE_COLORS } from "@/lib/graph-types"

export interface ContextMenuAction {
  id: string
  label: string
  icon: React.ElementType
  shortcut?: string
  danger?: boolean
  disabled?: boolean
}

export interface ContextMenuProps {
  x: number
  y: number
  node: GraphNodeType | null
  isOpen: boolean
  onClose: () => void
  onAction: (action: string, nodeId: string) => void
}

const nodeActions: ContextMenuAction[] = [
  { id: "expand", label: "Expand Connections", icon: Expand, shortcut: "E" },
  { id: "collapse", label: "Collapse", icon: Shrink, shortcut: "C" },
  { id: "focus", label: "Focus View", icon: Focus, shortcut: "F" },
  { id: "hide", label: "Hide Node", icon: EyeOff, shortcut: "H" },
  { id: "isolate", label: "Isolate Neighborhood", icon: Sparkles, shortcut: "I" },
  { id: "edit", label: "Edit Node", icon: Edit3, shortcut: "Enter" },
  { id: "pin", label: "Pin Position", icon: Lock, shortcut: "P" },
  { id: "copy", label: "Copy ID", icon: Copy, shortcut: "Cmd+C" },
  { id: "delete", label: "Delete Node", icon: Trash2, shortcut: "Del", danger: true },
]

const clusterActions: ContextMenuAction[] = [
  { id: "expand-cluster", label: "Expand Cluster", icon: Layers, shortcut: "E" },
  { id: "focus", label: "Focus Cluster", icon: Focus, shortcut: "F" },
  { id: "hide", label: "Hide Cluster", icon: EyeOff, shortcut: "H" },
]

const canvasActions: ContextMenuAction[] = [
  { id: "show-all", label: "Show All Nodes", icon: Eye },
  { id: "reset-view", label: "Reset View", icon: Expand },
  { id: "add-node", label: "Add New Node", icon: Sparkles },
]

export function ContextMenu({
  x,
  y,
  node,
  isOpen,
  onClose,
  onAction,
}: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)

  // Close on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose()
      }
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose()
      }
    }

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside)
      document.addEventListener("keydown", handleKeyDown)
    }

    return () => {
      document.removeEventListener("mousedown", handleClickOutside)
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [isOpen, onClose])

  // Adjust position to stay within viewport
  useEffect(() => {
    if (menuRef.current && isOpen) {
      const rect = menuRef.current.getBoundingClientRect()
      const viewportWidth = window.innerWidth
      const viewportHeight = window.innerHeight

      if (rect.right > viewportWidth) {
        menuRef.current.style.left = `${x - rect.width}px`
      }
      if (rect.bottom > viewportHeight) {
        menuRef.current.style.top = `${y - rect.height}px`
      }
    }
  }, [x, y, isOpen])

  const handleAction = useCallback(
    (actionId: string) => {
      onAction(actionId, node?.id || "")
      onClose()
    },
    [node, onAction, onClose]
  )

  if (!isOpen) return null

  const isCluster = node?.data?.isCluster
  const actions = node 
    ? (isCluster ? clusterActions : nodeActions)
    : canvasActions

  const kind = (node?.data?.kind || "entity") as NodeKind
  const colors = NODE_COLORS[kind] || NODE_COLORS.entity

  return (
    <div
      ref={menuRef}
      className="fixed z-50 min-w-[200px] py-1.5 bg-card/95 backdrop-blur-lg border border-border/60 rounded-xl shadow-2xl animate-in fade-in zoom-in-95 duration-100"
      style={{ left: x, top: y }}
    >
      {/* Node header */}
      {node && (
        <div className="px-3 py-2 border-b border-border/40">
          <div className="flex items-center gap-2">
            <div
              className="w-3 h-3 rounded-full"
              style={{
                background: colors.bg,
                boxShadow: `0 0 8px ${colors.glow}`,
              }}
            />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{node.data.label}</p>
              <p className="text-xs text-muted-foreground capitalize">
                {kind} {isCluster && `• ${node.data.clusterSize} nodes`}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="py-1">
        {actions.map((action, i) => {
          const Icon = action.icon
          return (
            <button
              key={action.id}
              onClick={() => handleAction(action.id)}
              disabled={action.disabled}
              className={`
                w-full flex items-center gap-3 px-3 py-2 text-sm transition-colors
                ${action.danger 
                  ? "text-destructive hover:bg-destructive/10" 
                  : "text-foreground hover:bg-secondary/60"
                }
                ${action.disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}
              `}
            >
              <Icon className="w-4 h-4 shrink-0" />
              <span className="flex-1 text-left">{action.label}</span>
              {action.shortcut && (
                <span className="text-xs text-muted-foreground font-mono">
                  {action.shortcut}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* Extra info for nodes */}
      {node && (
        <div className="px-3 py-2 border-t border-border/40">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>Connections: {node.data.degree || 0}</span>
            <span>Priority: {node.data.priority}</span>
          </div>
        </div>
      )}
    </div>
  )
}
