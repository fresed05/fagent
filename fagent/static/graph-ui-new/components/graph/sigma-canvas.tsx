"use client";

import { useEffect, useRef, useState } from "react";
import Sigma from "sigma";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import { RawNode, RawEdge } from "@/lib/graph-types";
import { createGraphFromData, SigmaNodeAttributes, SigmaEdgeAttributes } from "@/lib/sigma-utils";
import { getLODLevel, getNodeColor } from "@/lib/sigma-styles";

interface SigmaCanvasProps {
  rawNodes: RawNode[];
  rawEdges: RawEdge[];
  selectedNodeId?: string | null;
  onSelectNode?: (nodeId: string | null) => void;
  layoutMode?: "force" | "radial" | "hierarchical";
  onExpandCluster?: (clusterId: string) => void;
  onCollapseNodes?: (nodeIds: string[]) => void;
  hiddenNodeIds?: Set<string>;
}

export function SigmaCanvas({
  rawNodes,
  rawEdges,
  selectedNodeId,
  onSelectNode,
  layoutMode = "force",
  hiddenNodeIds = new Set(),
}: SigmaCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sigmaRef = useRef<Sigma<SigmaNodeAttributes, SigmaEdgeAttributes> | null>(null);
  const graphRef = useRef<Graph<SigmaNodeAttributes, SigmaEdgeAttributes> | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  // Инициализация графа и Sigma
  useEffect(() => {
    if (!containerRef.current) return;

    // Фильтровать скрытые узлы
    const visibleNodes = rawNodes.filter(n => !hiddenNodeIds.has(n.id));
    const visibleNodeIds = new Set(visibleNodes.map(n => n.id));
    const visibleEdges = rawEdges.filter(e => 
      visibleNodeIds.has(e.source_id) && visibleNodeIds.has(e.target_id)
    );

    // Создать граф
    const graph = createGraphFromData(visibleNodes, visibleEdges);
    graphRef.current = graph;

    // Инициализировать случайные координаты для узлов без позиций
    graph.forEachNode((node, attrs) => {
      if (attrs.x === undefined || attrs.y === undefined) {
        graph.setNodeAttribute(node, "x", Math.random() * 1000);
        graph.setNodeAttribute(node, "y", Math.random() * 1000);
      }
    });

    // Применить layout
    forceAtlas2.assign(graph, {
      iterations: 50,
      settings: {
        gravity: 1,
        scalingRatio: 10,
      },
    });

    // Инициализировать Sigma с настройками
    const sigma = new Sigma(graph, containerRef.current, {
      renderEdgeLabels: false,
      defaultNodeColor: "#64748b",
      defaultEdgeColor: "#64748b80",
      labelSize: 12,
      labelWeight: "600",
      labelColor: { color: "#e2e8f0" },
      edgeLabelSize: 10,
      stagePadding: 50,
    });

    sigmaRef.current = sigma;

    // Настроить камеру для плавного zoom
    const camera = sigma.getCamera();
    camera.animatedZoom({ duration: 300 });

    // Обработчики событий
    sigma.on("clickNode", ({ node }) => {
      onSelectNode?.(node);
    });

    sigma.on("enterNode", ({ node }) => {
      setHoveredNode(node);
      highlightNeighbors(node);
    });

    sigma.on("leaveNode", () => {
      setHoveredNode(null);
      resetHighlight();
    });

    return () => {
      sigma.kill();
    };
  }, [rawNodes, rawEdges, hiddenNodeIds]);

  // Обновить выделение при изменении selectedNodeId
  useEffect(() => {
    const graph = graphRef.current;
    const sigma = sigmaRef.current;
    if (!graph || !sigma) return;

    graph.forEachNode((node, attrs) => {
      if (node === selectedNodeId) {
        graph.setNodeAttribute(node, "color", getNodeColor(attrs.kind, "selected"));
        graph.setNodeAttribute(node, "size", attrs.size * 1.3);
      } else {
        graph.setNodeAttribute(node, "color", getNodeColor(attrs.kind, "default"));
        graph.setNodeAttribute(node, "size", attrs.size);
      }
    });

    sigma.refresh();
  }, [selectedNodeId]);

  // Подсветка соседей при hover
  const highlightNeighbors = (nodeId: string) => {
    const graph = graphRef.current;
    const sigma = sigmaRef.current;
    if (!graph || !sigma) return;

    const neighbors = new Set(graph.neighbors(nodeId));
    neighbors.add(nodeId);

    graph.forEachNode((node, attrs) => {
      if (neighbors.has(node)) {
        graph.setNodeAttribute(node, "color", getNodeColor(attrs.kind, "hover"));
      } else {
        graph.setNodeAttribute(node, "color", getNodeColor(attrs.kind, "dimmed"));
      }
    });

    sigma.refresh();
  };

  // Сброс подсветки
  const resetHighlight = () => {
    const graph = graphRef.current;
    const sigma = sigmaRef.current;
    if (!graph || !sigma) return;

    graph.forEachNode((node, attrs) => {
      graph.setNodeAttribute(node, "color", getNodeColor(attrs.kind, "default"));
    });

    sigma.refresh();
  };

  return (
    <div ref={containerRef} className="w-full h-full bg-background" />
  );
}
