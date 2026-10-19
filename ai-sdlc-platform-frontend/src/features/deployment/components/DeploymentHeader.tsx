import { Play } from "lucide-react";
import { useElapsed } from "@/shared/hooks";
import { useId } from "react";
import { Button } from "@/shared/ui/primitives";
import { Select } from "@/shared/ui/Select";
import { PhaseSectionHeader } from "@/shared/ui";
import type { ReleaseTarget, ReleaseTargetOption } from "../api/types";

/** Where a release goes, in the few words the header has room for. */
const SHORT_NAME: Record<ReleaseTarget, string> = {
  local: "This machine",
  cloud: "The cloud",
};

/**
 * The phase's title, its progress, and the one action that starts it again.
 *
 * The run button says what it does in words and is off while a run analyses or
 * a review waits: the server refuses both, and a button that invites a refusal
 * teaches the reader to ignore buttons.
 *
 * While a stage works the subtitle names it and says for how long, as Testing's
 * does: every stage of a run showed a spinner at once.
 */
export function DeploymentHeader({
  progress,
  isDark,
  canRun,
  runBlocked,
  running,
  version,
  onRun,
  targets,
  target,
  onChooseTarget,
  working,
}: {
  progress: number;
  isDark: boolean;
  canRun: boolean;
  /** Why the phase cannot start again now, shown where the controls are off. */
  runBlocked?: string;
  running: boolean;
  version: number;
  onRun: () => void;
  /** Where the next analysis plans the release for, chosen before it runs. */
  targets?: ReleaseTargetOption[];
  target?: ReleaseTarget;
  onChooseTarget?: (target: ReleaseTarget) => void;
  /** The stage a run is working on now, and since when, if the run says. */
  working?: { label: string; since: string | null };
}) {
  const targetId = useId();
  const workingFor = useElapsed(working?.since);
  // Beside "Analyse updates again", because the analysis plans for one target:
  // chosen only at the review, a change of target meant a second analysis.
  const choosing = version > 0 && targets && targets.length > 1 && target && onChooseTarget;
  return (
    <PhaseSectionHeader
      title="Deployment"
      subtitle={
        working
          ? `Working on ${working.label}${workingFor ? `, ${workingFor} so far` : ""}`
          : "Dependency updates assessed by three signals, released behind your review, and watched after release. Nothing ships and nothing rolls back without a person."
      }
      progress={progress}
      isDark={isDark}
      action={
        <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
          {choosing && (
            <div className="flex min-w-0 items-center gap-2 text-[12.5px] text-muted-foreground">
              <label htmlFor={targetId}>Release to</label>
              {/* Short names, and a width it cannot exceed: the full labels made
                  the header wider than the stage column at 768 pixels. Each
                  option carries its full label in the list, and its reason
                  when it cannot be used. */}
              <Select<ReleaseTarget>
                id={targetId}
                size="sm"
                className="max-w-[11rem]"
                value={target}
                disabled={!canRun || running}
                title={!canRun ? runBlocked : undefined}
                onChange={onChooseTarget}
                options={targets.map((one) => ({
                  value: one.id,
                  label: SHORT_NAME[one.id],
                  note: one.usable ? one.label : `${one.label}. Unavailable: ${one.reason}`,
                  disabled: !one.usable,
                }))}
              />
            </div>
          )}
          <Button
            variant="outline"
            onClick={onRun}
            disabled={!canRun || running}
            title={!canRun ? runBlocked : undefined}
          >
            <Play className="h-3.5 w-3.5" />
            {running ? "Analysing" : version > 0 ? "Analyse updates again" : "Analyse updates"}
          </Button>
        </div>
      }
    />
  );
}
