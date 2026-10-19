import { AlertTriangle, ArrowUpRight, Info, Play, Rocket, RefreshCw } from "lucide-react";
import { Button, Card } from "@/shared/ui/primitives";
import { Note } from "@/shared/ui/phase";
import type { ReleaseTarget, ReleaseTargetOption } from "../api/types";
import { ScopeField, TargetChoice } from "./RunSetup";

const willHappen = [
  "Find every newer release of the project's dependencies, and say which could not be assessed.",
  "Read each update's release notes, keeping a claim only when its quote is really in them.",
  "Trace what each update changes to the files and components of this project.",
  "Rate every update Low, Medium or High by the most cautious of three signals.",
  "Generate and validate the pipeline, build the candidate and verify it in staging.",
  "Prepare the rollback, then wait for your review before anything is released.",
];

/** Testing has not approved anything, so there is nothing this phase may deploy. */
export function PhaseWaitingOnTesting({
  projectName,
  onOpenTesting,
}: {
  projectName: string;
  onOpenTesting: () => void;
}) {
  return (
    <Card className="mx-auto max-w-3xl overflow-hidden">
      <div className="border-b border-slate-100 px-5 py-5 dark:border-white/[0.05]">
        <span className="mb-3 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 dark:bg-blue-500/15">
          <Rocket className="h-4 w-4 text-blue-600 dark:text-blue-300" />
        </span>
        <h3 className="text-[15px] font-semibold tracking-tight">
          Deployment has not started for {projectName}
        </h3>
        <Note className="mt-1.5 max-w-2xl">
          This phase deploys only code whose tests were reviewed and approved. Once Testing & Security
          approves a test run of the generated app, six things happen here, in this order.
        </Note>
      </div>
      <ol className="px-5 py-4">
        {willHappen.map((line, index) => (
          <li key={line} className="flex gap-3 py-2">
            <span className="tp-label mt-[3px] shrink-0">{String(index + 1).padStart(2, "0")}</span>
            <span className="tp-prose">{line}</span>
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-slate-100 bg-slate-50 px-5 py-3.5 dark:border-white/[0.05] dark:bg-white/[0.02]">
        <div className="min-w-0 flex-1">
          <p className="tp-label">Waiting on</p>
          <p className="mt-1 text-[13px]">
            Testing & Security: no test run of the generated app has been approved yet. An approved
            run on a sample does not count: it says nothing about this app.
          </p>
        </div>
        <Button variant="outline" onClick={onOpenTesting}>
          Open Testing & Security
          <ArrowUpRight className="h-3.5 w-3.5" />
        </Button>
      </div>
    </Card>
  );
}

/**
 * Tests are approved and nothing has been analysed yet.
 *
 * It said the approved tests measured the current code whatever they had
 * measured, and the run was then refused; and where the release would go, and
 * what to analyse, could be chosen only after the analysis that depends on
 * them. Then newer code with no approved tests took the run away, though the
 * tested code is what may ship.
 */
export function PhaseNotRun({
  onRun,
  busy,
  testVersion,
  testedCode,
  currentCode,
  targets,
  target,
  onChooseTarget,
  scopePackages,
  onChooseScope,
  onOpenTesting,
}: {
  onRun: () => void;
  busy: boolean;
  testVersion: number;
  /** The code version the approved tests measured: what the run analyses. */
  testedCode: number;
  /** The newest code version, tested or not. */
  currentCode: number;
  targets: ReleaseTargetOption[];
  target: ReleaseTarget;
  onChooseTarget: (target: ReleaseTarget) => void;
  scopePackages: string[];
  onChooseScope: (packages: string[]) => Promise<boolean>;
  onOpenTesting: () => void;
}) {
  const newer = currentCode > testedCode;
  return (
    <Card className="mx-auto max-w-2xl overflow-hidden">
      <div className="px-5 py-5">
        <h3 className="text-[15px] font-semibold tracking-tight">Ready to analyse the updates</h3>
        <Note className="mt-1.5">
          {newer
            ? `The approved tests (test version ${testVersion}) measured code version ${testedCode}, so this phase analyses and releases version ${testedCode}. Code version ${currentCode} is newer and waits for its own tests; once Testing & Security approves them, a run analyses it instead.`
            : `The approved tests (test version ${testVersion}) measured code version ${testedCode}, the current code, so this phase can start.`}{" "}
          The first run stops at the review; nothing is released until you approve it.
        </Note>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <TargetChoice targets={targets} value={target} disabled={busy} onChoose={onChooseTarget} />
          <ScopeField packages={scopePackages} disabled={busy} onSave={onChooseScope} />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="primary" onClick={onRun} busy={busy}>
            <Play className="h-3.5 w-3.5" />
            Analyse updates
          </Button>
          {newer && (
            <Button variant="outline" onClick={onOpenTesting}>
              Open Testing & Security
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}

/**
 * This analysis describes code that newer tested code replaced.
 *
 * The snapshot said so and nothing read it: an analysis of old code looked like
 * an analysis of the code that would ship.
 */
export function CodeMovedOnNotice({
  analysedCode,
  testedCode,
  reviewWaiting,
}: {
  analysedCode: number;
  /** The code version the newest approved tests measured. */
  testedCode: number;
  /** A review waits on the older analysis; analysing again closes it. */
  reviewWaiting: boolean;
}) {
  const closes = reviewWaiting ? ", which closes the review waiting on the older code" : "";
  return (
    <div
      role="status"
      className="flex flex-wrap items-start gap-3 rounded-2xl border border-amber-500/30 bg-amber-500/5 px-4 py-3"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
      <p className="min-w-0 flex-1 basis-60 text-[13px]">
        This analysis describes code version {analysedCode}, and code version {testedCode} has
        approved tests now: analyse the updates again{closes}.
      </p>
    </div>
  );
}

/**
 * Newer code waits for its own tests, and the tested code is what this phase
 * releases until they are approved. Newer code held every release back, and
 * the page then said to test it first; it now says which version ships.
 */
export function NewerCodeNotice({
  testedCode,
  newerCode,
  onOpenTesting,
}: {
  /** The code version the approved tests measured: what this phase releases. */
  testedCode: number;
  newerCode: number;
  onOpenTesting: () => void;
}) {
  return (
    <div
      role="status"
      className="flex flex-wrap items-start gap-3 rounded-2xl border border-blue-500/30 bg-blue-500/5 px-4 py-3"
    >
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-blue-600 dark:text-blue-300" />
      <p className="min-w-0 flex-1 basis-60 text-[13px]">
        Code version {newerCode} is newer and waits for its own tests. This phase releases code
        version {testedCode}, the newest with approved tests, until Testing & Security approves
        them.
      </p>
      <Button variant="outline" size="sm" onClick={onOpenTesting}>
        Open Testing & Security
        <ArrowUpRight className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

export function PhaseLoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <Card className="mx-auto max-w-2xl overflow-hidden">
      <div className="px-5 py-5">
        <span className="mb-3 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-red-50 dark:bg-red-500/10">
          <AlertTriangle className="h-4 w-4 text-red-600 dark:text-red-400" />
        </span>
        <h3 className="text-[15px] font-semibold tracking-tight">The deployment phase could not be loaded</h3>
        <Note className="mt-1.5">Nothing was changed and no decision was recorded.</Note>
        <Button variant="primary" className="mt-4" onClick={onRetry}>
          <RefreshCw className="h-3.5 w-3.5" />
          Try again
        </Button>
      </div>
    </Card>
  );
}
