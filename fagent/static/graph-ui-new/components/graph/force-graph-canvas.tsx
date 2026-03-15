"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { forceCollide } from "d3-force";
import { RawNode, RawEdge } from "@/lib/graph-types";
import { NODE_COLORS as _NODE_COLORS_SIGMA, NodeKind, calculateNodeSize } from "@/lib/sigma-styles";

// Safe color lookup: falls back to slate for unknown node kinds
const FALLBACK_COLOR = "#64748b";
function getNodeColor(kind: string): string {
  return (_NODE_COLORS_SIGMA as Record<string, string>)[kind] ?? FALLBACK_COLOR;
}

export interface NodeRightClickInfo {
  nodeId: string;
  nodeLabel: string;
  isCluster: boolean;
  clusterSize?: number;
  screenX: number;
  screenY: number;
}

interface ForceGraphCanvasProps {
  rawNodes: RawNode[];
  rawEdges: RawEdge[];
  selectedNodeId?: string | null;
  showLabels?: boolean;
  onSelectNode?: (nodeId: string | null) => void;
  onNodeRightClick?: (info: NodeRightClickInfo) => void;
  onExpandCluster?: (clusterId: string) => void;
  onCollapseNodes?: (nodeIds: string[]) => void;
  hiddenNodeIds?: Set<string>;
}

export function ForceGraphCanvas({
  rawNodes,
  rawEdges,
  selectedNodeId,
  showLabels = true,
  onSelectNode,
  onNodeRightClick,
  onExpandCluster,
  hiddenNodeIds = new Set(),
}: ForceGraphCanvasProps) {
  const fgRef = useRef<any>();
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [highlightNodes, setHighlightNodes] = useState<Set<string>>(new Set<string>());
  const [highlightLinks, setHighlightLinks] = useState<Set<string>>(new Set<string>());

  // Filter hidden nodes
  const visibleNodes = useMemo(() =>
    rawNodes.filter(n => !hiddenNodeIds.has(n.id)),
    [rawNodes, hiddenNodeIds]
  );

  const visibleNodeIds = useMemo(() =>
    new Set(visibleNodes.map(n => n.id)),
    [visibleNodes]
  );

  const visibleEdges = useMemo(() =>
    rawEdges.filter(e =>
      visibleNodeIds.has(e.source_id) && visibleNodeIds.has(e.target_id)
    ),
    [rawEdges, visibleNodeIds]
  );

  // Convert to force-graph format; tag clusters
  const graphData = useMemo(() => ({
    nodes: visibleNodes.map(node => ({
      id: node.id,
      name: node.label,
      kind: (node.metadata?.kind || "entity") as string,
      degree: node.degree || 0,
      priority_score: node.metadata?.priority_score || 5,
      cluster_size: node.metadata?.cluster_size as number | undefined,
      is_cluster: !!(node.metadata?.is_cluster || node.metadata?.kind === "cluster"),
    })),
    links: visibleEdges.map(edge => ({
      source: edge.source_id,
      target: edge.target_id,
      relation: edge.relation || "",
      weight: edge.weight || 1,
    })),
  }), [visibleNodes, visibleEdges]);

  // Hover highlight
  const handleNodeHover = useCallback((node: any) => {
    if (node) {
      setHoveredNode(node.id);
      const neighbors = new Set<string>();
      const links = new Set<string>();
      graphData.links.forEach(link => {
        const srcId = typeof link.source === "object" ? (link.source as any).id : link.source;
        const tgtId = typeof link.target === "object" ? (link.target as any).id : link.target;
        if (srcId === node.id) { neighbors.add(tgtId); links.add(`${node.id}-${tgtId}`); }
        if (tgtId === node.id) { neighbors.add(srcId); links.add(`${srcId}-${node.id}`); }
      });
      neighbors.add(node.id);
      setHighlightNodes(neighbors);
      setHighlightLinks(links);
    } else {
      setHoveredNode(null);
      setHighlightNodes(new Set());
      setHighlightLinks(new Set());
    }
  }, [graphData.links]);

  // Right-click handler
  const handleNodeRightClick = useCallback((node: any, event: MouseEvent) => {
    event.preventDefault();
    if (!onNodeRightClick) return;
    onNodeRightClick({
      nodeId: node.id as string,
      nodeLabel: node.name as string,
      isCluster: !!(node.is_cluster),
      clusterSize: node.cluster_size as number | undefined,
      screenX: event.clientX,
      screenY: event.clientY,
    });
  }, [onNodeRightClick]);

  // Double-click to expand cluster
  const handleNodeDoubleClick = useCallback((node: any) => {
    if (node.is_cluster && onExpandCluster) {
      onExpandCluster(node.id as string);
    }
  }, [onExpandCluster]);

  // Adaptive d3 forces
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    const nodeCount = graphData.nodes.length;
    const chargeStrength = nodeCount > 500 ? -600 : nodeCount > 200 ? -250 : -180;
    const linkDistance = nodeCount > 500 ? 150 : nodeCount > 200 ? 100 : 70;
    const linkStrength = nodeCount > 500 ? 0.5 : nodeCount > 200 ? 0.7 : 1;
    const centerStrength = nodeCount > 500 ? 0.02 : nodeCount > 200 ? 0.08 : 0.15;
    const collideRadius = nodeCount > 500 ? 30 : nodeCount > 200 ? 20 : 15;
    fg.d3Force("charge").strength(chargeStrength).distanceMin(20).distanceMax(500);
    fg.d3Force("link").distance(linkDistance).strength(linkStrength);
    fg.d3Force("center").strength(centerStrength);
    fg.d3Force("collide", forceCollide().radius(collideRadius).strength(1.0));
  }, [graphData.nodes.length]);

  const nodeCount = graphData.nodes.length;
  const warmupTicks = nodeCount > 500 ? 150 : nodeCount > 200 ? 100 : 50;
  const cooldownTicks = nodeCount > 500 ? 200 : nodeCount > 200 ? 150 : 100;

  return (
    <div ref={containerRef} style={{ width: "100%", height: "100%" }}>
      <ForceGraph2D
        ref={fgRef}
        graphData={graphData}
        nodeId="id"
        nodeLabel="name"
        nodeRelSize={6}
        warmupTicks={warmupTicks}
        cooldownTicks={cooldownTicks}
        nodeCanvasObject={(node: any, ctx, globalScale) => {
          if (!node || node.x === undefined || node.y === undefined || !isFinite(node.x) || !isFinite(node.y)) return;

          const sizeMultiplier = nodeCount > 1000 ? 0.7 : nodeCount > 500 ? 0.85 : 1;
          const size = calculateNodeSize(node.degree, node.cluster_size) * sizeMultiplier;
          if (!isFinite(size) || size <= 0) return;

          const isHighlighted = highlightNodes.has(node.id);
          const isSelected = node.id === selectedNodeId;
          const isDimmed = !!(hoveredNode && !isHighlighted);
          const isCluster = !!(node.is_cluster);
          const color = getNodeColor(node.kind as string);

          ctx.save();

          // Glow
          if (!isDimmed) {
            ctx.shadowBlur = isHighlighted || isSelected ? 24 : 12;
            ctx.shadowColor = color;
          }

          if (isCluster) {
            // Cluster: rounded rectangle
            const w = size * 2.4;
            const h = size * 1.6;
            const r = size * 0.35;
            const x = node.x - w / 2;
            const y = node.y - h / 2;

            ctx.beginPath();
            ctx.moveTo(x + r, y);
            ctx.lineTo(x + w - r, y);
            ctx.quadraticCurveTo(x + w, y, x + w, y + r);
            ctx.lineTo(x + w, y + h - r);
            ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
            ctx.lineTo(x + r, y + h);
            ctx.quadraticCurveTo(x, y + h, x, y + h - r);
            ctx.lineTo(x, y + r);
            ctx.quadraticCurveTo(x, y, x + r, y);
            ctx.closePath();

            const grad = ctx.createRadialGradient(node.x - w * 0.2, node.y - h * 0.2, 0, node.x, node.y, w * 0.7);
            grad.addColorStop(0, color + "ee");
            grad.addColorStop(1, color + "88");
            ctx.fillStyle = isDimmed ? color + "33" : grad;
            ctx.fill();

            if (isHighlighted || isSelected) {
              ctx.strokeStyle = "#ffffff";
              ctx.lineWidth = 2 / globalScale;
              ctx.stroke();
            }

            ctx.shadowBlur = 0;

            // Cluster count badge
            if (node.cluster_size) {
              const fontSize = Math.max(9, Math.min(14, size * 0.7)) / globalScale;
              ctx.font = `bold ${fontSize}px Inter, Sans-Serif`;
              ctx.textAlign = "center";
              ctx.textBaseline = "middle";
              ctx.fillStyle = isDimmed ? "rgba(255,255,255,0.3)" : "rgba(255,255,255,0.95)";
              ctx.fillText(String(node.cluster_size), node.x, node.y);
            }
          } else {
            // Regular node: circle
            const gradient = ctx.createRadialGradient(
              node.x - size * 0.3, node.y - size * 0.3, 0,
              node.x, node.y, size
            );
            gradient.addColorStop(0, color + "dd");
            gradient.addColorStop(1, color);

            ctx.beginPath();
            ctx.arc(node.x, node.y, size, 0, 2 * Math.PI);
            ctx.fillStyle = isDimmed ? color + "33" : gradient;
            ctx.fill();

            ctx.shadowBlur = 0;

            if (isHighlighted || isSelected) {
              ctx.strokeStyle = "#ffffff";
              ctx.lineWidth = 2 / globalScale;
              ctx.stroke();
            }
          }

          // Label — always if showLabels, else only on hover/select/zoom
          const shouldShowLabel = showLabels || isHighlighted || isSelected || globalScale > 1.5;
          if (shouldShowLabel) {
            const label = node.name;
            const fontSize = 12 / globalScale;
            ctx.font = `${isCluster ? "600" : "400"} ${fontSize}px Inter, Sans-Serif`;
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            const textWidth = ctx.measureText(label).width;
            const padding = 3 / globalScale;
            const labelY = node.y + (isCluster ? size * 0.8 + 4 / globalScale : size + 4 / globalScale);
            ctx.fillStyle = "rgba(0,0,0,0.75)";
            ctx.fillRect(
              node.x - textWidth / 2 - padding,
              labelY - padding,
              textWidth + padding * 2,
              fontSize + padding * 2
            );
            ctx.fillStyle = isDimmed ? "rgba(255,255,255,0.4)" : "#ffffff";
            ctx.fillText(label, node.x, labelY + fontSize / 2);
          }

          ctx.restore();
        }}
        linkCanvasObject={(link: any, ctx, globalScale) => {
          const sourceId = typeof link.source === "object" ? link.source.id : link.source;
          const targetId = typeof link.target === "object" ? link.target.id : link.target;
          const linkId = `${sourceId}-${targetId}`;
          const isHighlighted = highlightLinks.has(linkId);
          const isDimmed = !!(hoveredNode && !isHighlighted);

          const start = typeof link.source === "object" ? link.source : null;
          const end = typeof link.target === "object" ? link.target : null;
          if (!start || !end || start.x === undefined || end.x === undefined) return;

          const sourceNode = graphData.nodes.find(n => n.id === sourceId);
          const targetNode = graphData.nodes.find(n => n.id === targetId);

          if (isHighlighted) {
            ctx.strokeStyle = "#ffffff";
            ctx.lineWidth = 2 / globalScale;
            ctx.globalAlpha = 0.9;
          } else {
            const sourceColor = sourceNode ? getNodeColor(sourceNode.kind as string) : FALLBACK_COLOR;
            const targetColor = targetNode ? getNodeColor(targetNode.kind as string) : FALLBACK_COLOR;
            const gradient = ctx.createLinearGradient(start.x, start.y, end.x, end.y);
            gradient.addColorStop(0, sourceColor);
            gradient.addColorStop(1, targetColor);
            ctx.strokeStyle = gradient;
            ctx.lineWidth = 1.0 / globalScale;
            ctx.globalAlpha = isDimmed ? 0.06 : 0.45;
          }

          ctx.beginPath();
          ctx.moveTo(start.x, start.y);
          ctx.lineTo(end.x, end.y);
          ctx.stroke();
          ctx.globalAlpha = 1;
        }}
        onNodeClick={(node: any) => onSelectNode?.(node.id as string)}
        onNodeRightClick={handleNodeRightClick}
        onNodeDoubleClick={handleNodeDoubleClick}
        onNodeHover={handleNodeHover}
        onBackgroundClick={() => onSelectNode?.(null)}
        d3VelocityDecay={0.3}
      />
    </div>
  );
}
