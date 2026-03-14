import Graph from "graphology";
import { RawNode, RawEdge } from "./graph-types";
import {
  NODE_COLORS,
  NODE_BORDER_COLORS,
  calculateNodeSize,
  calculateEdgeOpacity,
  calculateEdgeSize,
  NodeKind,
} from "./sigma-styles";

export interface SigmaNodeAttributes {
  label: string;
  kind: NodeKind;
  size: number;
  color: string;
  borderColor: string;
  confidence: number;
  priority_score: number;
  degree: number;
  x?: number;
  y?: number;
  cluster_size?: number;
}

export interface SigmaEdgeAttributes {
  relation: string;
  weight: number;
  size: number;
  color: string;
}

// Конвертировать данные в Graphology граф
export function createGraphFromData(
  nodes: RawNode[],
  edges: RawEdge[]
): Graph<SigmaNodeAttributes, SigmaEdgeAttributes> {
  const graph = new Graph<SigmaNodeAttributes, SigmaEdgeAttributes>();

  // Добавить узлы
  nodes.forEach((node) => {
    const kind = (node.metadata?.kind || "entity") as NodeKind;
    const clusterSize = node.metadata?.cluster_size as number | undefined;
    const size = calculateNodeSize(node.degree || 0, clusterSize);
    
    graph.addNode(node.id, {
      label: node.label,
      kind,
      size,
      color: NODE_COLORS[kind],
      borderColor: NODE_BORDER_COLORS[kind],
      confidence: node.metadata?.confidence || 1,
      priority_score: node.metadata?.priority_score || 5,
      degree: node.degree || 0,
      cluster_size: clusterSize,
    });
  });

  // Добавить ребра
  edges.forEach((edge, index) => {
    if (graph.hasNode(edge.source_id) && graph.hasNode(edge.target_id)) {
      const edgeId = `${edge.source_id}-${edge.target_id}-${index}`;
      const weight = edge.weight || 1;
      
      graph.addEdgeWithKey(edgeId, edge.source_id, edge.target_id, {
        relation: edge.relation || "",
        weight,
        size: calculateEdgeSize(weight),
        color: "#64748b80",
      });
    }
  });

  return graph;
}

// Обновить позиции узлов в графе
export function updateNodePositions(
  graph: Graph<SigmaNodeAttributes, SigmaEdgeAttributes>,
  positions: Map<string, { x: number; y: number }>
): void {
  positions.forEach((pos, nodeId) => {
    if (graph.hasNode(nodeId)) {
      graph.setNodeAttribute(nodeId, "x", pos.x);
      graph.setNodeAttribute(nodeId, "y", pos.y);
    }
  });
}
