import { useCallback, useMemo, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Edge,
  type Node,
} from "reactflow";
import "reactflow/dist/style.css";
import { Check, Maximize2, Network, Pencil, Sparkles, X } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { StageSection, TraceChips } from "@/shared/ui/stage";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/shared/ui/primitives";
import { Chip, Hairline, Note, Panel } from "@/shared/ui/phase";
import { GraphCanvasModal } from "../graph/GraphCanvasModal";
import type {
  DesignSnapshot,
  GraphEdgeKind,
  GraphNode,
  GraphNodeKind,
} from "../../api/types";
import { graphNodeTypes } from "../graph/graphNodeTypes";
import {
  graphEdgeColors,
  graphNodeColors,
  type GraphNodeData,
} from "../graph/graphStyle";
import { scrollToSection } from "@/shared/hooks/useScrollSpy";

const nodeKindLabel: Record<GraphNodeKind, string> = {
  actor: "Actors",
  service: "Services",
  entity: "Things kept",
  constraint: "Rules",
};

const edgeKindLabel: Record<GraphEdgeKind, string> = {
  action: "Who does what",
  data: "Reads and writes",
  dependency: "Calls",
  constraint: "Rules applied",
};

const allNodeKinds = Object.keys(nodeKindLabel) as GraphNodeKind[];
const allEdgeKinds = Object.keys(edgeKindLabel) as GraphEdgeKind[];

export function StageArchitectureGraph({
  snapshot,
  isDark,
  onJump,
  onRename,
}: {
  snapshot: DesignSnapshot;
  isDark: boolean;
  onJump: (requirementId: string) => void;
  onRename: (nodeId: string, label: string) => void | Promise<unknown>;
}) {
  const [hiddenNodeKinds, setHiddenNodeKinds] = useState<GraphNodeKind[]>([]);
  const [hiddenEdgeKinds, setHiddenEdgeKinds] = useState<GraphEdgeKind[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  /**
   * Bring the detail panel into view when a node is chosen.
   *
   * The canvas is most of a screen tall, so the panel below it opened out of
   * sight and clicking a node looked like nothing had happened. The same scroll
   * and flash every other jump in this phase uses, so it reads as the same
   * action rather than a special case.
   */
  const selectNode = useCallback((nodeId: string) => {
    setSelectedId(nodeId);
    // After the panel has rendered with the new node in it.
    window.requestAnimationFrame(() => scrollToSection("graph-detail"));
  }, []);

  const graph = snapshot.graph;
  const changed = graph.changedNodeIds;

  const visibleNodes = useMemo(
    () => graph.nodes.filter((n) => !hiddenNodeKinds.includes(n.kind)),
    [graph.nodes, hiddenNodeKinds],
  );

  // Memoised on the arrays React Flow actually reads, so the canvas does not
  // relayout every time something elsewhere on the page changes.
  const flowNodes: Node<GraphNodeData>[] = useMemo(
    () =>
      visibleNodes.map((n) => ({
        id: n.id,
        type: "design",
        position: n.position,
        data: {
          label: n.label,
          kind: n.kind,
          isExternal: n.actorKind === "external_system",
          unconfirmed: n.unconfirmed,
          changed: changed.includes(n.id),
          selected: n.id === selectedId,
          onJumpToTrace: onJump,
          onSelect: () => selectNode(n.id),
        },
      })),
    [visibleNodes, changed, selectedId, onJump, selectNode],
  );

  const flowEdges: Edge[] = useMemo(() => {
    const visibleIds = new Set(visibleNodes.map((n) => n.id));
    return graph.edges
      .filter(
        (e) =>
          !hiddenEdgeKinds.includes(e.kind) &&
          visibleIds.has(e.source) &&
          visibleIds.has(e.target),
      )
      .map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.verb,
        animated: e.kind === "action",
        style: { stroke: graphEdgeColors[e.kind], strokeWidth: 1.5 },
        labelStyle: { fill: "#64748b", fontSize: 9 },
      }));
  }, [graph.edges, hiddenEdgeKinds, visibleNodes]);

  const selected = selectedId
    ? (graph.nodes.find((n) => n.id === selectedId) ?? null)
    : null;

  const toggle = <T,>(list: T[], value: T, set: (next: T[]) => void) =>
    set(
      list.includes(value) ? list.filter((v) => v !== value) : [...list, value],
    );

  // One definition, rendered in the card or in the window. Two copies would
  // drift, and rebuilding it for the modal would drop the filters and the
  // selection the reader had already set.
  const [expanded, setExpanded] = useState(false);

  const canvas = (
    <ReactFlow
      nodes={flowNodes}
      edges={flowEdges}
      nodeTypes={graphNodeTypes}
      onNodeClick={(_, node) => selectNode(node.id)}
      onPaneClick={() => setSelectedId(null)}
      // The canvas made each node a focusable button around the node's own
      // controls, a button inside a button; each card carries its own instead.
      nodesFocusable={false}
      fitView
      fitViewOptions={{ padding: 0.2 }}
    >
      <Background color={isDark ? "#1e293b" : "#cbd5e1"} gap={20} />
      <Controls />
      <MiniMap
        nodeColor={(n) =>
          graphNodeColors[(n.data as GraphNodeData)?.kind] ?? "#64748b"
        }
        maskColor={isDark ? "rgba(15,23,42,0.7)" : "rgba(248,250,252,0.7)"}
      />
    </ReactFlow>
  );

  return (
    <div className="space-y-5">
      {changed.length > 0 && (
        <div className="flex items-start gap-2.5 rounded-2xl border border-amber-500/30 bg-amber-500/5 px-4 py-3">
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-amber-500 dark:text-amber-400" />
          <div className="min-w-0">
            <p className="text-[13px] font-semibold text-[color:var(--tp-ink)]">
              {changed.length} {changed.length === 1 ? "node" : "nodes"} changed
              in this version
            </p>
            <Note className="mt-1">
              Ringed in amber on the canvas:{" "}
              {changed
                .map((id) => graph.nodes.find((n) => n.id === id)?.label ?? id)
                .join(", ")}
              .
            </Note>
          </div>
        </div>
      )}

      <StageSection id="graph-canvas">
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
              <div className="min-w-0">
                <CardTitle className="flex items-center gap-2">
                  <Network className="h-4 w-4 text-green-500" />
                  Semantic Architecture Graph (SAG)
                </CardTitle>
                <p className="mt-1 text-xs text-[color:var(--tp-ink-2)]">
                  One typed graph of the system. The domain model, the class
                  diagram and the sequence diagrams are all generated from it,
                  so nothing here can drift from them.
                </p>
              </div>
              <p className="tp-den shrink-0">
                {visibleNodes.length} of {graph.nodes.length} nodes,{" "}
                {flowEdges.length} of {graph.edges.length} edges
              </p>
            </div>

            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2">
              <FilterGroup
                label="Show"
                options={allNodeKinds.map((kind) => ({
                  id: kind,
                  label: nodeKindLabel[kind],
                  color: graphNodeColors[kind],
                  on: !hiddenNodeKinds.includes(kind),
                }))}
                onToggle={(id) =>
                  toggle(
                    hiddenNodeKinds,
                    id as GraphNodeKind,
                    setHiddenNodeKinds,
                  )
                }
              />
              <FilterGroup
                label="Links"
                options={allEdgeKinds.map((kind) => ({
                  id: kind,
                  label: edgeKindLabel[kind],
                  color: graphEdgeColors[kind],
                  on: !hiddenEdgeKinds.includes(kind),
                }))}
                onToggle={(id) =>
                  toggle(
                    hiddenEdgeKinds,
                    id as GraphEdgeKind,
                    setHiddenEdgeKinds,
                  )
                }
              />
              <button
                type="button"
                onClick={() => setExpanded(true)}
                aria-label="Open the graph larger"
                title="Open larger"
                className="flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-lg border border-[color:var(--tp-line)] text-[color:var(--tp-muted)] transition-colors hover:border-blue-500/50 hover:text-blue-600"
              >
                <Maximize2 className="h-3.5 w-3.5" />
              </button>
            </div>
          </CardHeader>

          <CardContent className="p-0">
            <div
              className={cn(
                "h-[52vh] min-h-[320px] w-full md:h-[480px]",
                isDark ? "bg-[#0a0e17]" : "bg-slate-50",
              )}
            >
              {expanded ? null : canvas}
            </div>
          </CardContent>

          {expanded && (
            <GraphCanvasModal
              title="Architecture Graph"
              isDark={isDark}
              onClose={() => setExpanded(false)}
            >
              {canvas}
            </GraphCanvasModal>
          )}
        </Card>
      </StageSection>

      <StageSection id="graph-detail">
        {selected ? (
          <NodeDetail
            node={selected}
            snapshot={snapshot}
            onClose={() => setSelectedId(null)}
            onJump={onJump}
            onRename={onRename}
          />
        ) : (
          <Panel label="Node detail">
            <Note>
              Select a node on the canvas to see what it is, what it traces to,
              and what it connects to.
            </Note>
          </Panel>
        )}
      </StageSection>
    </div>
  );
}

function FilterGroup({
  label,
  options,
  onToggle,
}: {
  label: string;
  options: { id: string; label: string; color: string; on: boolean }[];
  onToggle: (id: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="tp-label">{label}</span>
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          aria-pressed={option.on}
          onClick={() => onToggle(option.id)}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors",
            option.on
              ? "border-[color:var(--tp-line-strong)] text-[color:var(--tp-ink)]"
              : "border-[color:var(--tp-line)] text-[color:var(--tp-muted)] line-through",
          )}
        >
          <span
            className="h-2 w-2 rounded-full"
            style={{
              backgroundColor: option.on ? option.color : "transparent",
              border: `1px solid ${option.color}`,
            }}
          />
          {option.label}
        </button>
      ))}
    </div>
  );
}

function NodeDetail({
  node,
  snapshot,
  onClose,
  onJump,
  onRename,
}: {
  node: GraphNode;
  snapshot: DesignSnapshot;
  onClose: () => void;
  onJump: (requirementId: string) => void;
  onRename: (nodeId: string, label: string) => void | Promise<unknown>;
}) {
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState(node.label);

  const connections = snapshot.graph.edges
    .filter((e) => e.source === node.id || e.target === node.id)
    .map((e) => {
      const otherId = e.source === node.id ? e.target : e.source;
      const other = snapshot.graph.nodes.find((n) => n.id === otherId);
      return {
        id: e.id,
        outgoing: e.source === node.id,
        verb: e.verb,
        other: other?.label ?? otherId,
        kind: e.kind,
      };
    });

  const constrainedBy = snapshot.graph.nodes.filter(
    (n) => n.kind === "constraint" && n.appliesTo.includes(node.id),
  );

  return (
    <Panel
      label={node.label}
      title={node.description}
      meta={`${node.kind}${node.standard ? ` · ${node.standard}` : ""}`}
      action={
        <div className="flex gap-2">
          {!renaming && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setDraft(node.label);
                setRenaming(true);
              }}
            >
              <Pencil className="h-3.5 w-3.5" />
              Rename
            </Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            aria-label="Close node detail"
            onClick={onClose}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      }
    >
      {renaming && (
        <div className="mb-4 rounded-xl border border-blue-500/30 bg-blue-500/[0.05] px-3.5 py-3">
          <label className="tp-label block" htmlFor="node-rename">
            New name
          </label>
          <input
            id="node-rename"
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="mt-1.5 w-full rounded-lg border border-[color:var(--tp-line)] bg-transparent px-3 py-1.5 text-[13px] outline-none focus:border-blue-500/50"
          />
          <Note className="mt-1.5">
            The domain model and the diagrams read this graph, so renaming here
            changes all of them at once. Nothing has to be renamed twice.
          </Note>
          <div className="mt-2.5 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="primary"
              disabled={!draft.trim() || draft.trim() === node.label}
              onClick={async () => {
                try {
                  await onRename(node.id, draft.trim());
                  setRenaming(false);
                } catch {
                  // Reported where it failed; the box stays open with the name.
                }
              }}
            >
              <Check className="h-3.5 w-3.5" />
              Rename
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setRenaming(false)}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <div>
          <p className="tp-label">Traces to</p>
          <div className="mt-1.5">
            <TraceChips traces={node.traces} onJump={onJump} />
          </div>

          {node.attributes.length > 0 && (
            <>
              <Hairline className="my-3.5" />
              <p className="tp-label">Attributes</p>
              <ul className="mt-1.5 space-y-1">
                {node.attributes.map((attribute) => (
                  <li
                    key={attribute.name}
                    className="tp-mono text-[12px] text-[color:var(--tp-ink-2)]"
                  >
                    {attribute.name}
                    <span className="text-[color:var(--tp-muted)]">
                      {" "}
                      : {attribute.type}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}

          {node.appliesTo.length > 0 && (
            <>
              <Hairline className="my-3.5" />
              <p className="tp-label">Constrains</p>
              <p className="tp-den mt-1.5">
                {node.appliesTo
                  .map(
                    (id) =>
                      snapshot.graph.nodes.find((n) => n.id === id)?.label ??
                      id,
                  )
                  .join(", ")}
              </p>
            </>
          )}

          {constrainedBy.length > 0 && (
            <>
              <Hairline className="my-3.5" />
              <p className="tp-label">Rules that apply here</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {constrainedBy.map((c) => (
                  <Chip key={c.id} tone="caution">
                    {c.label}
                  </Chip>
                ))}
              </div>
            </>
          )}

          {node.unconfirmed && (
            <>
              <Hairline className="my-3.5" />
              <p className="tp-label">Needs a closer look</p>
              <Note className="mt-1.5">{node.unconfirmed.reason}</Note>
              <Note className="mt-1">
                The rule that noticed is{" "}
                <span className="tp-mono">{node.unconfirmed.ruleId}</span>. It
                did not stop the design being generated; it means this node is
                worth reading before you approve.
              </Note>
              {node.unconfirmed.traces.length > 0 && (
                <div className="mt-1.5">
                  <TraceChips
                    traces={node.unconfirmed.traces}
                    onJump={onJump}
                    label="Read from"
                  />
                </div>
              )}
            </>
          )}
        </div>

        <div>
          <p className="tp-label">Connections</p>
          <ul className="mt-1.5 space-y-1">
            {connections.map((c) => (
              <li
                key={c.id}
                className="text-[12.5px] leading-relaxed text-[color:var(--tp-ink-2)]"
              >
                <span
                  className="mr-1.5 inline-block h-2 w-2 rounded-full align-middle"
                  style={{ backgroundColor: graphEdgeColors[c.kind] }}
                />
                {c.outgoing ? (
                  <>
                    <span className="text-[color:var(--tp-ink)]">
                      {node.label}
                    </span>{" "}
                    {c.verb}{" "}
                    <span className="text-[color:var(--tp-ink)]">
                      {c.other}
                    </span>
                  </>
                ) : (
                  <>
                    <span className="text-[color:var(--tp-ink)]">
                      {c.other}
                    </span>{" "}
                    {c.verb}{" "}
                    <span className="text-[color:var(--tp-ink)]">
                      {node.label}
                    </span>
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Panel>
  );
}
