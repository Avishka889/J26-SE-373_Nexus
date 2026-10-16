import { AlertTriangle, ArrowUpRight, FlaskConical, Play, RefreshCw } from "lucide-react";
import { Button, Card } from "@/shared/ui/primitives";
import { Note } from "./bits/index";

const willHappen = [
  "Write unit and API tests from the requirements and the code, then run them.",
  "Triage every failure: repair the brittle tests, route the real regressions to a developer untouched.",
  "Measure line coverage, branch coverage, and how many planted bugs the tests catch.",
  "Scan for security issues with a local model and an AI reviewer, then combine the results.",
  "Prove each applied fix twice: the scan runs again, and so does the whole suite.",
  "Roll all of it into one report for you to approve before Deployment starts.",
];

/**
 * A phase with no run yet. What it waits on depends on the code review: before
 * it approves a build there is nothing to test, and after it the only thing
 * missing is a person starting the first run, which this offers in place.
 */
export function PhaseNotStarted({
  projectName,
  codeApproved,
  running,
  onOpenCode,
  onRun,
}: {
  projectName: string;
  /** Whether the code review approved a build, which is all a first run needs. */
  codeApproved: boolean;
  running: boolean;
  onOpenCode: () => void;
  onRun: () => void;
}) {
  return (
    <Card className="mx-auto max-w-3xl overflow-hidden">
      <div className="border-b border-slate-100 px-5 py-5 dark:border-white/[0.05]">
        <span className="mb-3 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 dark:bg-blue-500/15">
          <FlaskConical className="h-4 w-4 text-blue-600 dark:text-blue-300" />
        </span>
        <h3 className="text-[15px] font-semibold tracking-tight">Testing has not started for {projectName}</h3>
        <Note className="mt-1.5 max-w-2xl">
          {codeApproved
            ? "This phase runs on the build the code review approved. Once you start a run, six things happen here, in this order."
            : "This phase runs on a build the code review approved. Once Code Generation has one, six things happen here, in this order."}
        </Note>
      </div>

      <ol className="px-5 py-4">
        {willHappen.map((line, i) => (
          <li key={line} className="flex gap-3 py-2">
            <span className="tp-label mt-[3px] shrink-0">{String(i + 1).padStart(2, "0")}</span>
            <span className="tp-prose">{line}</span>
          </li>
        ))}
      </ol>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-slate-100 bg-slate-50 px-5 py-3.5 dark:border-white/[0.05] dark:bg-white/[0.02]">
        {codeApproved ? (
          <>
            <div className="min-w-0 flex-1">
              <p className="tp-label">Ready</p>
              <p className="mt-1 text-[13px]">
                The code review approved this build. Nothing runs until you start it.
              </p>
            </div>
            <Button variant="primary" onClick={onRun} disabled={running}>
              <Play className="h-3.5 w-3.5" />
              {running ? "Running…" : "Run tests"}
            </Button>
          </>
        ) : (
          <>
            <div className="min-w-0 flex-1">
              <p className="tp-label">Waiting on</p>
              <p className="mt-1 text-[13px]">
                Code Generation: its review has not approved a build yet.
              </p>
            </div>
            <Button variant="outline" onClick={onOpenCode}>
              Open Code Generation
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Button>
          </>
        )}
      </div>
    </Card>
  );
}

export function PhaseLoadError({ message, onRetry }: { message?: string; onRetry: () => void }) {
  return (
    <Card className="mx-auto max-w-2xl overflow-hidden">
      <div className="px-5 py-5">
        <span className="mb-3 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-red-50 dark:bg-red-500/10">
          <AlertTriangle className="h-4 w-4 text-red-600 dark:text-red-400" />
        </span>
        <h3 className="text-[15px] font-semibold tracking-tight">We could not load this project's tests</h3>
        <Note className="mt-1.5">
          The numbers on this page would be incomplete, so none are shown. Nothing was changed and no
          decision was recorded.
        </Note>
        {message && (
          <p className="mt-3 rounded-lg bg-slate-50 px-3 py-2 font-mono text-[11.5px] text-slate-600 dark:bg-white/[0.03] dark:text-slate-400">
            {message}
          </p>
        )}
        <Button variant="primary" className="mt-4" onClick={onRetry}>
          <RefreshCw className="h-3.5 w-3.5" />
          Try again
        </Button>
      </div>
    </Card>
  );
}
