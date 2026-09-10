import type { GraphEdgeKind, GraphNodeKind, ValidationFinding } from "../../api/types";

/** One colour per kind, shared by the canvas, the minimap and the filters. */
export const graphNodeColors: Record<GraphNodeKind, string> = {
  actor: "#22c55e",
  entity: "#3b82f6",
  service: "#2563eb",
  constraint: "#f97316",
};

export const graphEdgeColors: Record<GraphEdgeKind, string> = {
  action: "#22c55e",
  data: "#3b82f6",
  dependency: "#64748b",
  constraint: "#f97316",
};

export type GraphNodeData = {
  label: string;
  kind: GraphNodeKind;
  isExternal: boolean;
  /** Null when every rule check confirmed the node, which is the normal case. */
  unconfirmed: ValidationFinding | null;
  changed: boolean;
  selected: boolean;
  /** Opens the requirement the finding concerns, so the warning goes somewhere. */
  onJumpToTrace: (requirementId: string) => void;
  /** Shows this node's detail: the card's own button, so a keyboard can do it. */
  onSelect: () => void;
};
