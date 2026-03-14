"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { forceCollide } from "d3-force";
import { RawNode, RawEdge } from "@/lib/graph-types";
import { NODE_COLORS as _NODE_COLORS_SIGMA, NodeKind, calculateNodeSize } from "@/lib/sigma-styles";

// Safe color lookup: falls back to 'entity' color for unknown node kinds
const FALLBACK_COLOR = "#64748b";
function getNodeColor(kind: string): string {
  return (_NODE_COLORS_SIGMA as Record<string, string>)[kind] ?? FALLBACK_COLOR;
}

interface ForceGraphCanvasProps {
  rawNodes: RawNode[];
  rawEdges: RawEdge[];
  selectedNodeId?: string | null;
  onSelectNode?: (nodeId: string | null) => void;
  layoutMode?: "force" | "radial" | "hierarchical";
  onExpandCluster?: (clusterId: string) => void;
  onCollapseNodes?: (nodeIds: string[]) => void;
  hiddenNodeIds?: Set<string>;
}

export function ForceGraphCanvas({
  rawNodes,
  rawEdges,
  selectedNodeId,
  onSelectNode,
  hiddenNodeIds = new Set(),
}: ForceGraphCanvasProps) {
  const fgRef = useRef<any>();
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [highlightNodes, setHighlightNodes] = useState<Set<string>>(new Set<string>());
  const [highlightLinks, setHighlightLinks] = useState<Set<string>>(new Set<string>());

  // Фильтровать скрытые узлы
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

  // Конвертировать в формат force-graph
  const graphData = useMemo(() => ({
    nodes: visibleNodes.map(node => ({
      id: node.id,
      name: node.label,
      kind: (node.metadata?.kind || "entity") as NodeKind,
      degree: node.degree || 0,
      priority_score: node.metadata?.priority_score || 5,
      cluster_size: node.metadata?.cluster_size as number | undefined,
    })),
    links: visibleEdges.map(edge => ({
      source: edge.source_id,
      target: edge.target_id,
      relation: edge.relation || "",
      weight: edge.weight || 1,
    })),
  }), [visibleNodes, visibleEdges]);

  // Обработчик hover
  const handleNodeHover = useCallback((node: any) => {
    if (node) {
      setHoveredNode(node.id);
      const neighbors = new Set<string>();
      const links = new Set<string>();
      
      graphData.links.forEach(link => {
        if (link.source === node.id || (link.source as any).id === node.id) {
          const targetId = typeof link.target === 'object' ? (link.target as any).id : link.target;
          neighbors.add(targetId);
          links.add(`${node.id}-${targetId}`);
        }
        if (link.target === node.id || (link.target as any).id === node.id) {
          const sourceId = typeof link.source === 'object' ? (link.source as any).id : link.source;
          neighbors.add(sourceId);
          links.add(`${sourceId}-${node.id}`);
        }
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

  // Настроить d3 силы адаптивно на основе количества узлов
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;

    const nodeCount = graphData.nodes.length;
    
    // Адаптивные параметры на основе размера графа (увеличенные расстояния)
    const chargeStrength = nodeCount > 500 ? -600 : nodeCount > 200 ? -250 : -150;
    const linkDistance = nodeCount > 500 ? 150 : nodeCount > 200 ? 100 : 60;
    const linkStrength = nodeCount > 500 ? 0.5 : nodeCount > 200 ? 0.7 : 1;
    const centerStrength = nodeCount > 500 ? 0.02 : nodeCount > 200 ? 0.08 : 0.15;
    const collideRadius = nodeCount > 500 ? 30 : nodeCount > 200 ? 20 : 15;
    
    // Настроить силы
    fg.d3Force('charge')
      .strength(chargeStrength)
      .distanceMin(20)
      .distanceMax(500);
    
    fg.d3Force('link')
      .distance(linkDistance)
      .strength(linkStrength);
    
    fg.d3Force('center').strength(centerStrength);
    
    fg.d3Force('collide', forceCollide()
      .radius(collideRadius)
      .strength(1.0));
  }, [graphData.nodes.length]);

  // Адаптивные параметры симуляции
  const nodeCount = graphData.nodes.length;
  const warmupTicks = nodeCount > 500 ? 150 : nodeCount > 200 ? 100 : 50;
  const cooldownTicks = nodeCount > 500 ? 200 : nodeCount > 200 ? 150 : 100;

  return (
    <ForceGraph2D
      ref={fgRef}
      graphData={graphData}
      nodeId="id"
      nodeLabel="name"
      nodeRelSize={6}
      warmupTicks={warmupTicks}
      cooldownTicks={cooldownTicks}
      nodeCanvasObject={(node: any, ctx, globalScale) => {
        // Проверка валидности координат
        if (!node || node.x === undefined || node.y === undefined || !isFinite(node.x) || !isFinite(node.y)) {
          return;
        }
        
        // Адаптивный размер для больших графов
        const sizeMultiplier = nodeCount > 1000 ? 0.7 : nodeCount > 500 ? 0.85 : 1;
        const size = calculateNodeSize(node.degree, node.cluster_size) * sizeMultiplier;
        
        // Проверка валидности размера
        if (!isFinite(size) || size <= 0) {
          return;
        }
        
        const isHighlighted = highlightNodes.has(node.id);
        const isSelected = node.id === selectedNodeId;
        const isDimmed = hoveredNode && !isHighlighted;
        
        // Цвет узла
        const color = getNodeColor(node.kind as string);
        
        // Glow эффект
        if (!isDimmed) {
          ctx.shadowBlur = isHighlighted || isSelected ? 20 : 10;
          ctx.shadowColor = color;
        }
        
        // Градиент для объемности
        const gradient = ctx.createRadialGradient(
          node.x - size * 0.3, node.y - size * 0.3, 0,
          node.x, node.y, size
        );
        const lighterColor = color + 'dd';
        gradient.addColorStop(0, lighterColor);
        gradient.addColorStop(1, color);
        
        // Рисовать узел
        ctx.beginPath();
        ctx.arc(node.x, node.y, size, 0, 2 * Math.PI);
        ctx.fillStyle = isDimmed ? color + '33' : gradient;
        ctx.fill();
        
        // Сбросить shadow
        ctx.shadowBlur = 0;
        
        // Обводка при hover или selection
        if (isHighlighted || isSelected) {
          ctx.strokeStyle = '#ffffff';
          ctx.lineWidth = 2 / globalScale;
          ctx.stroke();
        }
        
        // Label
        if (isHighlighted || isSelected || globalScale > 1.5) {
          const label = node.name;
          const fontSize = 12 / globalScale;
          ctx.font = `${fontSize}px Sans-Serif`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          
          // Фон для label
          const textWidth = ctx.measureText(label).width;
          const padding = 4 / globalScale;
          ctx.fillStyle = 'rgba(0, 0, 0, 0.8)';
          ctx.fillRect(
            node.x - textWidth / 2 - padding,
            node.y + size + 4 / globalScale - padding,
            textWidth + padding * 2,
            fontSize + padding * 2
          );
          
          // Текст label
          ctx.fillStyle = '#ffffff';
          ctx.fillText(label, node.x, node.y + size + fontSize / 2 + 4 / globalScale);
        }
      }}
      linkCanvasObject={(link: any, ctx, globalScale) => {
        const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
        const targetId = typeof link.target === 'object' ? link.target.id : link.target;
        const linkId = `${sourceId}-${targetId}`;
        const isHighlighted = highlightLinks.has(linkId);
        const isDimmed = hoveredNode && !isHighlighted;
        
        const start = typeof link.source === 'object' ? link.source : null;
        const end = typeof link.target === 'object' ? link.target : null;
        
        // Проверка координат
        if (!start || !end || start.x === undefined || end.x === undefined) return;
        
        // Найти узлы для получения цветов
        const sourceNode = graphData.nodes.find(n => n.id === sourceId);
        const targetNode = graphData.nodes.find(n => n.id === targetId);
        
        if (isHighlighted) {
          // Подсвеченная связь - белая, яркая
          ctx.strokeStyle = '#ffffff';
          ctx.lineWidth = 2 / globalScale;
          ctx.globalAlpha = 0.9;
        } else {
          // Градиент от цвета source к цвету target
          const sourceColor = sourceNode ? getNodeColor(sourceNode.kind as string) : FALLBACK_COLOR;
          const targetColor = targetNode ? getNodeColor(targetNode.kind as string) : FALLBACK_COLOR;
          
          const gradient = ctx.createLinearGradient(start.x, start.y, end.x, end.y);
          gradient.addColorStop(0, sourceColor);
          gradient.addColorStop(1, targetColor);
          
          ctx.strokeStyle = gradient;
          ctx.lineWidth = 1.0 / globalScale;
          ctx.globalAlpha = isDimmed ? 0.08 : 0.45;
        }
        
        // Рисовать линию
        ctx.beginPath();
        ctx.moveTo(start.x, start.y);
        ctx.lineTo(end.x, end.y);
        ctx.stroke();
        
        // Сбросить alpha
        ctx.globalAlpha = 1;
      }}
      onNodeClick={(node) => onSelectNode?.(node.id as string)}
      onNodeHover={handleNodeHover}
      onBackgroundClick={() => onSelectNode?.(null)}
      d3VelocityDecay={0.3}
    />
  );
}
