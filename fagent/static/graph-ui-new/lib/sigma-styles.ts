import { NodeDisplayData, EdgeDisplayData } from "sigma/types";

export type NodeKind = "entity" | "fact" | "episode" | "cluster" | "bridge";

// Цветовая схема по типам узлов
export const NODE_COLORS: Record<NodeKind, string> = {
  entity: "#10b981",    // emerald-500
  fact: "#f97316",      // orange-500
  episode: "#3b82f6",   // blue-500
  cluster: "#a855f7",   // purple-500
  bridge: "#64748b",    // slate-500
};

// Темные версии для обводки
export const NODE_BORDER_COLORS: Record<NodeKind, string> = {
  entity: "#064e3b",
  fact: "#7c2d12",
  episode: "#1e3a5f",
  cluster: "#4c1d95",
  bridge: "#1e293b",
};

// Вычисление размера узла на основе degree
export function calculateNodeSize(degree: number, clusterSize?: number): number {
  if (clusterSize) {
    return Math.min(40, 20 + clusterSize * 0.5);
  }
  
  const baseSize = 4;
  const scaleFactor = 0.6;
  return Math.min(32, baseSize + degree * scaleFactor);
}

// Получить цвет узла с учетом состояния
export function getNodeColor(
  kind: NodeKind,
  state: "default" | "hover" | "selected" | "dimmed"
): string {
  const baseColor = NODE_COLORS[kind];
  
  switch (state) {
    case "hover":
      return lightenColor(baseColor, 20);
    case "selected":
      return baseColor;
    case "dimmed":
      return baseColor + "33"; // 20% opacity
    default:
      return baseColor;
  }
}

// Осветлить цвет на процент
function lightenColor(hex: string, percent: number): string {
  const num = parseInt(hex.replace("#", ""), 16);
  const r = Math.min(255, ((num >> 16) & 0xff) + (255 * percent) / 100);
  const g = Math.min(255, ((num >> 8) & 0xff) + (255 * percent) / 100);
  const b = Math.min(255, (num & 0xff) + (255 * percent) / 100);
  
  return `#${Math.round(r).toString(16).padStart(2, "0")}${Math.round(g).toString(16).padStart(2, "0")}${Math.round(b).toString(16).padStart(2, "0")}`;
}

// Вычислить прозрачность ребра на основе weight
export function calculateEdgeOpacity(weight: number): number {
  return Math.max(0.3, Math.min(0.7, weight / 10));
}

// Вычислить толщину ребра на основе weight
export function calculateEdgeSize(weight: number): number {
  return Math.max(1, Math.min(4, weight / 2));
}

// LOD система - определить уровень детализации на основе zoom
export function getLODLevel(zoom: number): "high" | "medium" | "low" {
  if (zoom > 1.5) return "high";
  if (zoom > 0.5) return "medium";
  return "low";
}
