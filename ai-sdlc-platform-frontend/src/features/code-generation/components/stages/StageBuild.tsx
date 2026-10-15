import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  ExternalLink,
  GitBranch,
  RotateCcw,
  Upload,
} from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { Button } from "@/shared/ui/primitives";
import { Note, Panel } from "@/shared/ui/phase";
import { Console, transcriptOf } from "@/shared/ui/console";
import { StageSection } from "@/shared/ui/stage";
import type { BuildStepReport, CodeSnapshot } from "../../api/types";

/**
 * The build, and where the code went.
 *
 * Every outcome here is what happened rather than what was expected: a step
 * that never ran says `not-run`, a step that hit its cap says `timed-out`, and
 * neither is ever shown as passed. The isolation is described in words,
 * including what it does not guarantee, because a sandbox that overstates
 * itself is worse than one that is honest about being a subprocess.
 *
 * If nothing was pushed, this says why. It never shows a repository URL that
 * does not exist.
 */
const OUTCOME_TONE: Record<string, string> = {
  passed: "text-emerald-700 dark:text-emerald-400",
  failed: "text-red-600 dark:text-red-400",
  "timed-out": "text-red-600 dark:text-red-400",
  "not-run": "text-[color:var(--tp-muted)]",
};

const OUTCOME_WORDS: Record<string, string> = {
  passed: "passed",
  failed: "failed",
  "timed-out": "hit its time cap",
  "not-run": "never ran, because a step before it failed",
};

export function StageBuild({
  snapshot,
  preview,
  approved,
  githubConnected,
  onPush,
  onDownload,
  onBuildAgain,
}: {
  snapshot: CodeSnapshot;
  /** The preview panel, passed in so this stage stays a pure view of the
   *  build report and does not reach for a project id it has no use for. */
  preview?: ReactNode;
  /** The code review approved the version on screen. */
  approved: boolean;
  /** Whether GitHub is connected; null until the connections are read. */
  githubConnected: boolean | null;
  /** Push the version, which was never pushed: the only remedy was a new run. */
  onPush: () => Promise<void>;
  /** The version's generated files as a zip, GitHub or not. */
  onDownload: () => Promise<void>;
  /** Run the build again: one that ran and did not pass had no way on but a
   *  whole new generation. */
  onBuildAgain?: () => Promise<unknown>;
}) {
  const [busy, setBusy] = useState<"push" | "download" | "build" | null>(null);
  const act = async (which: "push" | "download" | "build", action: () => Promise<unknown>) => {
    setBusy(which);
    try {
      await action();
    } finally {
      setBusy(null);
    }
  };
  const repository = snapshot.repository;
  if (!repository) return null;
  const pointer = repository.repository;
  const ownBranch = Boolean(pointer?.branch) && pointer?.branch !== pointer?.defaultBranch;
  const build = repository.build;
  const passed = Boolean(build?.steps.length) && build!.steps.every((s) => s.outcome === "passed");

  return (
    <div className="space-y-5">
      <StageSection id="build-steps">
        <Panel
          label="Build"
          title={build?.toolchain ?? "No build has run yet."}
          icon={
            passed ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />
          }
        >
          {!build ? (
            <Note>
              {snapshot.approvedThrough
                ? "Not built on its own: an accepted security fix wrote this version from the files of the version it patched. Testing and Security builds and runs it, and so does Deployment's staging build."
                : "Nothing has been built yet."}
            </Note>
          ) : (
            <>
              <ul className="space-y-1.5">
                {build.steps.map((step) => (
                  <StepRow key={step.name} step={step} />
                ))}
              </ul>

              <Console
                className="mt-3 max-h-[320px]"
                label="Build transcript"
                meta={build.toolchain}
                lines={transcriptOf(build.steps)}
              />

              <Note className="mt-3">{build.isolation}</Note>
              {!passed && !approved && onBuildAgain && (
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-3"
                  busy={busy === "build"}
                  onClick={() => void act("build", onBuildAgain)}
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Build again
                </Button>
              )}
            </>
          )}
        </Panel>
      </StageSection>

      <StageSection id="build-repository">
        <Panel
          label="Repository"
          icon={<GitBranch className="h-4 w-4" />}
          action={
            <Button
              variant="outline"
              size="sm"
              busy={busy === "download"}
              onClick={() => void act("download", onDownload)}
            >
              <Download className="h-3.5 w-3.5" />
              Download the code
            </Button>
          }
        >
          {pointer ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <a
                  href={pointer.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 text-[13px] font-medium text-blue-600 underline decoration-dotted underline-offset-2 dark:text-blue-300"
                >
                  {pointer.owner}/{pointer.name}
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
                <span className="tp-mono text-[11px] text-[color:var(--tp-ink-2)]">
                  {ownBranch ? pointer.branch : pointer.defaultBranch} · {pointer.commitSha.slice(0, 7)}
                </span>
              </div>
              {ownBranch && (
                // Every version went to the default branch, unreviewed and
                // failing ones included.
                <Note className="mt-2">
                  {approved
                    ? `Approved, so ${pointer.defaultBranch} carries this version; the conversation says when it moved, or why it could not.`
                    : `On a branch of its own. ${pointer.defaultBranch} moves to it when the code review approves it, and not before.`}
                </Note>
              )}
            </>
          ) : (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-3.5 py-3">
              <p className="text-[13px] font-semibold text-[color:var(--tp-ink)]">
                Nothing was pushed
              </p>
              <Note className="mt-1">
                {repository.notPushedReason ??
                  "No reason was recorded, which is itself a defect worth reporting."}
              </Note>
              {githubConnected ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-2"
                  busy={busy === "push"}
                  onClick={() => void act("push", onPush)}
                >
                  <Upload className="h-3.5 w-3.5" />
                  Push this version
                </Button>
              ) : (
                <Note className="mt-2">
                  <Link to="/settings?tab=git" className="text-blue-700 underline dark:text-blue-300">
                    Connect GitHub in Settings
                  </Link>{" "}
                  to push this version without generating it again, or download the code above.
                </Note>
              )}
            </div>
          )}
          <Note className="mt-3">
            {repository.manifest.length} files were generated. The push is one commit on one
            tree, so what is in the repository is exactly what the manifest lists.
          </Note>
        </Panel>
      </StageSection>

      {preview}
    </div>
  );
}

function StepRow({ step }: { step: BuildStepReport }) {
  return (
    <li className="flex flex-wrap items-baseline gap-2 rounded-lg border border-[color:var(--tp-line)] px-3 py-2">
      <span className="text-[13px] font-medium text-[color:var(--tp-ink)]">{step.name}</span>
      <span className="tp-mono text-[11px] text-[color:var(--tp-muted)]">{step.command}</span>
      <span className={cn("ml-auto text-[12px] font-medium", OUTCOME_TONE[step.outcome])}>
        {OUTCOME_WORDS[step.outcome] ?? step.outcome}
      </span>
      {step.durationSeconds !== null && step.durationSeconds !== undefined && (
        <span className="tp-den">{step.durationSeconds.toFixed(1)}s</span>
      )}
    </li>
  );
}
