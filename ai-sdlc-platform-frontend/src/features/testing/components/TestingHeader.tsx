import { Play } from "lucide-react";
import { useElapsed } from "@/shared/hooks";
import { useId } from "react";
import { Button } from "@/shared/ui/primitives";
import { Select } from "@/shared/ui/Select";
import { ChevronStepper } from "@/shared/ui/ChevronStepper";
import { PhaseSectionHeader } from "@/shared/ui";
import type { TestTarget } from "../api/types";
import type { StepId } from "../model/view";
import { StickyHeader } from "./PhaseChrome";

type StepperStep = { id: string; label: string; badge?: number };

/**
 * The phase's title, what it measures, and the way to run it: the first run,
 * or running again.
 *
 * The run button showed on the loading and error screens and before any run,
 * where it could do nothing useful; while a review waited the server refused it
 * and nothing said why; and a long run said "Running" with no sense of how long.
 * The first run started from the foot of the not-started card, out of sight
 * below the six steps it describes, where Code Generation's starts from its
 * header; it starts here now, once the code review approved a build.
 *
 * While a stage works the subtitle names it and says for how long: every stage
 * of a run showed a spinner at once, and on the live run Test Generation waited
 * three minutes on the model with nothing on the page to say so.
 */
export function TestingHeader({
  progress,
  progressLabel,
  isDark,
  running,
  onStart,
  onRerun,
  rerunBlocked,
  runningSince,
  working,
  target,
  targets,
  onChooseTarget,
}: {
  progress: number;
  /** The progress in a word ("Needs attention"), where the number alone misleads. */
  progressLabel?: string;
  isDark: boolean;
  running: boolean;
  /** The first run, offered only before any run and once the code review approved a build. */
  onStart?: () => void;
  /** Absent where running again means nothing: loading, a failed read, no run yet. */
  onRerun?: () => void;
  /** Why running again is refused now, said beside the button. */
  rerunBlocked?: string;
  /** When the run in progress started, for the elapsed time. */
  runningSince?: string | null;
  /** The stage a run is working on now, and since when, if the run says. */
  working?: { label: string; since: string | null };
  target?: string;
  targets?: TestTarget[];
  onChooseTarget?: (target: string) => void;
}) {
  const targetId = useId();
  const elapsed = useElapsed(running ? runningSince : null);
  const workingFor = useElapsed(working?.since);
  return (
    <PhaseSectionHeader
      title="Testing & Security"
      subtitle={
        working
          ? `Working on ${working.label}${workingFor ? `, ${workingFor} so far` : ""}`
          : "Tests are written from the requirements, run, and triaged. Every repair and every fix has to prove itself before you approve the phase."
      }
      progress={progress}
      valueLabel={progressLabel}
      roomyTitle
      isDark={isDark}
      // Wraps, and every child may shrink. At 390 the selector and the run
      // button sat side by side and pushed the column six pixels past the
      // viewport, which the narrow width sweep caught the first time it was
      // allowed to look at this phase.
      //
      // The reason a run is held sits under the controls, not in their row. A
      // wrapping row is as wide as all its items on one line when its width is
      // asked for, so the sentence made the whole block 808px wide.
      action={
        <div className="flex min-w-0 max-w-full flex-col items-end gap-1.5">
        <div data-run-controls className="flex min-w-0 max-w-full flex-wrap items-center justify-end gap-2">
          {targets && targets.length > 1 && onChooseTarget ? (
            <div className="flex min-w-0 items-center gap-2 text-[12.5px] text-muted-foreground">
              {/* Which repository every number below is about. Beside the run
                  button because it decides what running measures, and a
                  coverage figure for one repository beside a test count for
                  another would be two facts about two programs in one panel. */}
              <label htmlFor={targetId}>Measuring</label>
              <Select
                id={targetId}
                size="sm"
                value={target ?? "generated"}
                disabled={running}
                onChange={onChooseTarget}
                options={targets.map((one) => ({ value: one.id, label: one.label, note: one.detail }))}
              />
            </div>
          ) : null}
          {onStart && (
            <Button variant="primary" onClick={onStart}>
              <Play className="h-3.5 w-3.5" />
              Run tests
            </Button>
          )}
          {onRerun && (
            <Button
              variant="outline"
              onClick={onRerun}
              disabled={running || Boolean(rerunBlocked)}
              title={rerunBlocked}
              aria-describedby={rerunBlocked ? "rerun-blocked" : undefined}
            >
              <Play className="h-3.5 w-3.5" />
              {running ? `Running${elapsed ? ` for ${elapsed}` : "…"}` : "Run tests again"}
            </Button>
          )}
        </div>
          {onRerun && rerunBlocked && !running && (
            <span id="rerun-blocked" className="tp-den max-w-[26rem] text-right text-[12px]">
              {rerunBlocked}
            </span>
          )}
        </div>
      }
    />
  );
}

export function TestingStepper({
  steps,
  progressId,
  selectedId,
  isDark,
  onStepClick,
}: {
  steps: StepperStep[];
  progressId: string;
  selectedId: StepId;
  isDark: boolean;
  onStepClick: (id: StepId) => void;
}) {
  return (
    <StickyHeader>
      <ChevronStepper
        steps={steps}
        progressId={progressId}
        selectedId={selectedId}
        isDark={isDark}
        onStepClick={(id) => onStepClick(id as StepId)}
      />
    </StickyHeader>
  );
}
