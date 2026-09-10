import { Handle, Position, type NodeProps } from "reactflow";
import { AlertCircle, Box, Database, Plug, User } from "lucide-react";
import type { GraphNodeKind } from "../../api/types";
import { graphNodeColors, type GraphNodeData } from "./graphStyle";

const nodeIcons: Record<GraphNodeKind, typeof User> = {
  actor: User,
  entity: Database,
  service: Box,
  constraint: AlertCircle,
};

export function GraphNodeCard({ data }: NodeProps<GraphNodeData>) {
  const Icon = data.isExternal ? Plug : (nodeIcons[data.kind] ?? Box);
  const color = graphNodeColors[data.kind] ?? "#64748b";
  const finding = data.unconfirmed;
  const firstTrace = finding?.traces[0];

  return (
    <div
      className="rounded-lg border-2 bg-slate-900 px-3 py-2 shadow-lg"
      style={{
        borderColor: data.selected ? "#60a5fa" : color,
        minWidth: 118,
        // A node the current version changed is worth spotting at a glance.
        boxShadow: data.changed ? "0 0 0 3px rgba(245,158,11,0.45)" : undefined,
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: color }} />
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          data.onSelect();
        }}
        aria-pressed={data.selected}
        className="flex items-center gap-2 rounded text-left outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
      >
        <Icon aria-hidden="true" className="h-3.5 w-3.5 shrink-0" style={{ color }} />
        <span className="text-xs font-medium text-white">{data.label}</span>
      </button>

      {/* Plain words, and it goes somewhere. The old label read "NOT VALIDATED"
          with no explanation anywhere on the page, which told the reader
          something was wrong without telling them what or where to look. */}
      {finding && (
        <button
          type="button"
          title={
            `${finding.reason}\n\n` +
            `Rule: ${finding.ruleId}\n` +
            (firstTrace
              ? `Read from ${finding.traces.join(", ")}. Click to open ${firstTrace}.`
              : "No requirement is named for this one.")
          }
          onClick={(event) => {
            event.stopPropagation();
            if (firstTrace) data.onJumpToTrace(firstTrace);
          }}
          className="mt-1 flex items-center gap-1 rounded text-[9px] font-medium uppercase tracking-wide text-amber-400 transition-colors hover:text-amber-300"
        >
          <AlertCircle className="h-2.5 w-2.5 shrink-0" />
          Needs a closer look
        </button>
      )}

      <Handle type="source" position={Position.Right} style={{ background: color }} />
    </div>
  );
}
