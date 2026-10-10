import { useState } from "react";
import { LayoutGrid, Monitor, TriangleAlert } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { StageSection, TraceChips } from "@/shared/ui/stage";
import { Button } from "@/shared/ui/primitives";
import { Bar, Chip, Metric, Note, Panel } from "@/shared/ui/phase";
import type { DesignSnapshot } from "../../api/types";
import { ScreenMiniature } from "../wireframes/ScreenPreview";
import { WireframeFlowModal } from "../wireframes/WireframeFlowModal";

export function StageWireframes({
  snapshot,
  projectName,
  isDark,
  onJump,
  onRequestRefinement,
  linkedScreenId,
}: {
  snapshot: DesignSnapshot;
  projectName: string;
  isDark: boolean;
  onJump: (requirementId: string) => void;
  onRequestRefinement: (flowId: string, note: string) => void | Promise<unknown>;
  /** A screen another page linked to: its flow opens at it. */
  linkedScreenId?: string | null;
}) {
  const { flows, coverage } = snapshot.wireframes;
  const [openFlowId, setOpenFlowId] = useState<string | null>(
    () =>
      flows.find((flow) => flow.screens.some((screen) => screen.id === linkedScreenId))?.id ?? null,
  );

  // Only the stories a person performs are scored. Work no actor owns, such as
  // ingesting telemetry or syncing an ERP, could never have a screen, and
  // counting it as uncovered reported a gap that was not there. Those rows stay
  // below, because a machine decided this and a reader has to be able to
  // disagree with it.
  const scored = coverage.filter((row) => row.needsScreen);
  const covered = scored.filter((row) => row.covered);
  const uncovered = scored.filter((row) => !row.covered);
  const noScreenNeeded = coverage.filter((row) => !row.needsScreen);
  const screenCount = flows.reduce((sum, flow) => sum + flow.screens.length, 0);
  const source = `Wireframes, design version ${snapshot.requirementsVersion}`;
  const openFlow = flows.find((f) => f.id === openFlowId) ?? null;

  return (
    <div className="space-y-5">
      <StageSection id="wireframes-coverage">
        <Panel
          icon={<LayoutGrid className="h-4 w-4" />}
          label="Coverage"
          title="Whether the screens actually cover the work that was planned."
        >
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Metric source={source} label="Flows" value={flows.length} size="sm" />
            <Metric source={source} label="Screens" value={screenCount} size="sm" />
            <Metric
              source={source}
              label="Stories covered"
              value={covered.length}
              denominator={`of ${scored.length}`}
              tone={uncovered.length === 0 ? "pass" : "caution"}
              size="sm"
            />
            <div className="min-w-0">
              <p className="tp-label">Coverage</p>
              <Bar
                value={scored.length ? Math.round((covered.length / scored.length) * 100) : 0}
                tone={uncovered.length === 0 ? "pass" : "caution"}
                className="mt-2"
              />
            </div>
          </div>

          {uncovered.length > 0 && (
            <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-amber-500/30 bg-amber-500/5 px-3.5 py-3">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-500 dark:text-amber-400" />
              <div className="min-w-0">
                <p className="text-[13px] font-semibold text-[color:var(--tp-ink)]">
                  {uncovered.length} {uncovered.length === 1 ? "story has" : "stories have"} no screen yet
                </p>
                <ul className="mt-1 space-y-0.5">
                  {uncovered.map((row) => (
                    <li key={row.storyId} className="tp-den">
                      <span className="tp-mono">{row.storyId}</span> {row.storyTitle}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {noScreenNeeded.length > 0 && (
            <div className="mt-3 rounded-xl border border-[color:var(--tp-line)] px-3.5 py-3">
              <p className="tp-den">
                {noScreenNeeded.length}{" "}
                {noScreenNeeded.length === 1 ? "story needs" : "stories need"} no screen: no
                actor performs {noScreenNeeded.length === 1 ? "it" : "them"}.
              </p>
              <ul className="mt-1 space-y-0.5">
                {noScreenNeeded.map((row) => (
                  <li key={row.storyId} className="tp-den">
                    <span className="tp-mono">{row.storyId}</span> {row.storyTitle}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Panel>
      </StageSection>

      <StageSection id="wireframes-flows" className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">
        {flows.map((flow) => (
          /* The whole card opens the player. Not a <button> around it, because
             the card holds trace chips and a button of its own and nesting those
             is invalid markup that swallows their clicks. A click handler on the
             region plus the real button inside keeps both the large target and
             the keyboard path. */
          <div
            key={flow.id}
            onClick={() => setOpenFlowId(flow.id)}
            className="cursor-pointer"
          >
          <Panel
            label={flow.name}
            title={`${flow.screens.length} ${flow.screens.length === 1 ? "screen" : "screens"}`}
            className="flex h-full flex-col transition-colors hover:border-blue-500/40"
            bodyClassName="flex flex-1 flex-col gap-3"
          >
            {/* The real screen, scaled. A card can never show something the
                player does not, because it is the same component. */}
            <div
              className={cn(
                "h-[170px] overflow-hidden rounded-xl border",
                isDark ? "border-white/10 bg-[#0b1524]" : "border-slate-200 bg-slate-50",
              )}
            >
              <ScreenMiniature screen={flow.screens[0]} isDark={isDark} />
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <Chip>{flow.version}</Chip>
              {flow.pendingRefinement && (
                <Chip tone="caution" title={flow.refinementNote ?? undefined}>
                  Refinement requested
                </Chip>
              )}
            </div>

            <TraceChips traces={flow.traces} onJump={onJump} />

            <div className="mt-auto">
              <Button size="sm" variant="outline" onClick={() => setOpenFlowId(flow.id)}>
                <Monitor className="h-3.5 w-3.5" />
                Click through it
              </Button>
            </div>
          </Panel>
          </div>
        ))}
      </StageSection>

      <Note>
        Asking for a refinement changes one flow. Approving the design happens once, at Design Review.
      </Note>

      {openFlow && (
        <WireframeFlowModal
          flow={openFlow}
          projectName={projectName}
          isOpen
          isDark={isDark}
          onClose={() => setOpenFlowId(null)}
          onRequestRefinement={(note) => onRequestRefinement(openFlow.id, note)}
          initialScreenId={linkedScreenId}
        />
      )}
    </div>
  );
}
