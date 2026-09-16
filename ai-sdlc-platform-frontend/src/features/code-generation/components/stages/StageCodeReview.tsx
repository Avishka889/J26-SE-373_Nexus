import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ExternalLink,
  History,
  } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { Button } from "@/shared/ui/primitives";
import { ActorMark, Metric, Note, Panel } from "@/shared/ui/phase";
import { StageSection } from "@/shared/ui/stage";
import type { CodeStageId } from "@/types/project";
import type { CodeSnapshot } from "../../api/types";
import { usePreview } from "../../hooks/useCode";
import { CODE_STAGE_META } from "../../model/stages";
import { inferredBy } from "../../model/arms";
import { Spinner } from "@/shared/ui/Spinner";
import { formatWhen } from "@/shared/utils/time";

/**
 * Everything above in one place, and the decision that starts Testing.
 *
 * A view over the other stages rather than an artefact of its own, so nothing
 * here is generated and nothing here can be stale on its own. What it adds is
 * the summary a person needs to decide: what was built, from which contract,
 * whether the code and the contract agree, whether it builds, where it went,
 * and whether it is running.
 *
 * The one thing here that can disagree with the snapshot is the preview,
 * because it is a process rather than a row: it says which code version it is
 * serving, so a reviewer is never shown an older app beside a newer report.
 *
 * Once the code is approved, the way on to Testing and Security is here, as
 * Requirements and Design offers the way on to Code Generation.
 */
export function StageCodeReview({
  projectId,
  snapshot,
  onOpenStage,
  onContinue,
}: {
  projectId: string;
  snapshot: CodeSnapshot;
  onOpenStage: (id: CodeStageId) => void;
  onContinue: () => void;
}) {
  const scope = snapshot.scope;
  const contract = snapshot.contract;
  const agreement = snapshot.agreement;
  const repository = snapshot.repository;
  const inScope = (scope?.stories ?? []).filter((story) => story.inScope);
  const errors = (agreement?.findings ?? []).filter((finding) => finding.severity === "error");
  const warnings = (agreement?.findings ?? []).filter((f) => f.severity === "warning");
  const buildPassed =
    Boolean(repository?.build?.steps.length) &&
    (repository?.build?.steps ?? []).every((step) => step.outcome === "passed");

  const decision = snapshot.gate.decision;

  return (
    <div className="space-y-5">
      {decision?.kind === "approved" && (
        <Panel className="border-emerald-500/30 bg-emerald-500/[0.04]">
          <div className="flex flex-wrap items-start gap-3">
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" />
            <div className="min-w-0 flex-1">
              <p className="text-[15px] font-semibold text-[color:var(--tp-ink)]">
                Code approved for code version {decision.version}
              </p>
              <p className="tp-den mt-1 flex flex-wrap items-center gap-1.5">
                <ActorMark actor={decision.by} kind="human" /> at {formatWhen(decision.at)}
              </p>
              <Note className="mt-2">
                If the code changes after this, the approval covers the version it was given for
                and this phase asks again.
              </Note>
              <Button variant="primary" className="mt-3" onClick={onContinue}>
                Continue to Testing &amp; Security
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </Panel>
      )}
      {!decision && snapshot.approvedThrough ? (
        <Panel className="border-emerald-500/30 bg-emerald-500/[0.04]">
          <div className="flex flex-wrap items-start gap-3">
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" />
            <div className="min-w-0 flex-1">
              <p className="text-[15px] font-semibold text-[color:var(--tp-ink)]">
                Code version {snapshot.codeVersion} is approved through code version{" "}
                {snapshot.approvedThrough}
              </p>
              <Note className="mt-2">
                An accepted security fix wrote it, so it has no review of its own: the approval
                of the version it patched covers it. Run the tests on it to see the fix hold.
              </Note>
              <Button variant="primary" className="mt-3" onClick={onContinue}>
                Continue to Testing &amp; Security
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </Panel>
      ) : null}

      <StageSection id="review-summary">
        <Panel label="What is being reviewed" title={`Code version ${snapshot.codeVersion}`}>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Metric source={`Sprint Scope, code version ${snapshot.codeVersion}`} label="Stories" value={String(inScope.length)} />
            <Metric source={`API Contract, code version ${snapshot.codeVersion}`} label="Endpoints" value={String(contract?.contract.endpoints.length ?? 0)} />
            <Metric source={`the files generated at code version ${snapshot.codeVersion}`} label="Files" value={String(repository?.manifest.length ?? 0)} />
            <Metric
              source={`the run that wrote code version ${snapshot.codeVersion}`}
              label="Generated from"
              value={`design v${snapshot.generatedFromDesignVersion}`}
            />
          </div>
          {snapshot.generatedFromDesignVersion < snapshot.designVersion && (
            <div className="mt-3 flex items-start gap-2.5 rounded-xl border border-amber-500/30 bg-amber-500/5 px-3.5 py-3">
              <History className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
              <div>
                <p className="text-[13px] font-semibold text-[color:var(--tp-ink)]">
                  The design has moved on since this code was generated
                </p>
                <Note className="mt-1">
                  This was generated from design version {snapshot.generatedFromDesignVersion} and
                  the design is now at {snapshot.designVersion}. Approving records a decision
                  about the older design, which may be exactly what you want; generating again
                  reads the newer one.
                </Note>
              </div>
            </div>
          )}
        </Panel>
      </StageSection>

      <StageSection id="review-evidence">
        <Panel label="The evidence">
          <ul className="space-y-2">
            <Evidence
              ok={Boolean(contract)}
              onOpen={() => onOpenStage("api-contract")}
              stage="api-contract"
              line={
                contract
                  ? `${contract.contract.endpoints.length} endpoints, ${inferredBy(contract.chosen)}` +
                    (contract.comparison
                      ? `, arms agree on ${Math.round(contract.comparison.agreementRate * 100)}% of the union`
                      : "")
                  : "No contract was inferred, so there is nothing to review."
              }
            />
            <Evidence
              ok={errors.length === 0 && Boolean(agreement)}
              onOpen={() => onOpenStage("contract-agreement")}
              stage="contract-agreement"
              line={
                agreement
                  ? `${Math.round(agreement.counts.agreementRate * 100)}% of the contract's routes are registered` +
                    (errors.length ? `, ${errors.length} errors to read` : "") +
                    (warnings.length ? `, ${warnings.length} warnings` : "")
                  : "The agreement check did not run, so nothing has been validated."
              }
            />
            <Evidence
              ok={buildPassed}
              onOpen={() => onOpenStage("build")}
              stage="build"
              line={
                repository?.build
                  ? repository.build.steps
                      .map((step) => `${step.name} ${step.outcome}`)
                      .join(", ")
                  : "Nothing has been built."
              }
            />
            <Evidence
              ok={Boolean(repository?.repository)}
              onOpen={() => onOpenStage("build")}
              stage="build"
              line={
                repository?.repository
                  ? `Pushed to ${repository.repository.owner}/${repository.repository.name}`
                  : (repository?.notPushedReason ?? "Nothing was pushed.")
              }
            />
            <PreviewEvidence
              projectId={projectId}
              buildPassed={buildPassed}
              codeVersion={snapshot.codeVersion}
              onOpen={() => onOpenStage("build")}
            />
          </ul>
          <Note className="mt-3">
            A warning is not a blocker and an error is not a veto: this is the decision, and
            the record will say what was known when it was made.
          </Note>
        </Panel>
      </StageSection>

      <StageSection id="review-decision">
        <Panel label="Decision">
          {snapshot.gate.decision ? (
            <div className="rounded-xl border border-[color:var(--tp-line-strong)] px-3.5 py-3">
              <p className="text-[13px] font-semibold text-[color:var(--tp-ink)]">
                {snapshot.gate.decision.kind === "approved"
                  ? "Approved"
                  : "Changes requested"}{" "}
                by {snapshot.gate.decision.by}
              </p>
              <Note className="mt-1">
                Code version {snapshot.gate.decision.version}
                {snapshot.gate.decision.note ? `. ${snapshot.gate.decision.note}` : ""}
              </Note>
            </div>
          ) : snapshot.approvedThrough ? (
            // A version an accepted security fix wrote has no review of its own,
            // and the page read it as undecided, with nowhere to decide.
            <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/[0.04] px-3.5 py-3">
              <p className="text-[13px] font-semibold text-[color:var(--tp-ink)]">
                Approved through code version {snapshot.approvedThrough}
              </p>
              <Note className="mt-1">
                An accepted security fix wrote code version {snapshot.codeVersion}, so it has no
                review of its own: the approval of the version it patched covers it, and the fix
                itself was decided in Testing and Security.
              </Note>
            </div>
          ) : (
            <Note>
              Nothing has been decided yet. The decision bar at the bottom of this page is
              where it happens, and approving is what starts Testing and Security.
            </Note>
          )}

          {snapshot.gate.history.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {snapshot.gate.history.map((decision, index) => (
                <li key={`${decision.version}-${index}`} className="tp-den">
                  v{decision.version}: {decision.kind === "approved" ? "approved" : "changes"} by{" "}
                  {decision.by}
                  {decision.note ? ` (${decision.note})` : ""}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </StageSection>
    </div>
  );
}

/**
 * The running app, from the page where the decision is made.
 *
 * Reading the diff and the agreement report tells a reviewer what was built;
 * only the running app tells them whether it works. The lifecycle stays in
 * Build, which owns starting and stopping it, so this is a link and a status
 * rather than a second set of controls: two places to start the same process
 * is how you end up with two of them.
 */
function PreviewEvidence({
  projectId,
  buildPassed,
  codeVersion,
  onOpen,
}: {
  projectId: string;
  buildPassed: boolean;
  codeVersion: number;
  onOpen: () => void;
}) {
  const { data: preview } = usePreview(projectId);
  const status = preview?.status ?? "none";
  const running = status === "running" && Boolean(preview?.url);
  const stale = running && preview?.codeVersion !== codeVersion;

  if (status === "unavailable") return null;

  if (running) {
    return (
      <li className="flex items-start gap-2.5 rounded-xl border border-[color:var(--tp-line)] px-3.5 py-2.5">
        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
        <span className="min-w-0 flex-1">
          <span className="block text-[13px] font-medium text-[color:var(--tp-ink)]">Preview</span>
          <span className="tp-den">
            {stale
              ? `Running code version ${preview?.codeVersion}, which is not the ${codeVersion} under review.`
              : `Running on ${preview?.url}`}
          </span>
        </span>
        <a
          href={preview?.url ?? "#"}
          target="_blank"
          rel="noreferrer"
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-500/[0.07] px-2.5 py-1.5 text-[12.5px] font-medium text-blue-600 transition-colors hover:border-blue-500/70 dark:text-blue-300"
        >
          Open the app
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </li>
    );
  }

  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full cursor-pointer items-start gap-2.5 rounded-xl border border-[color:var(--tp-line)] px-3.5 py-2.5 text-left transition-colors hover:border-blue-500/40"
      >
        {status === "starting" ? (
          <Spinner size="sm" decorative className="mt-0.5 text-[color:var(--tp-ink-2)]" />
        ) : (
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
        )}
        <span className="min-w-0 flex-1">
          <span className="block text-[13px] font-medium text-[color:var(--tp-ink)]">Preview</span>
          <span className="tp-den">
            {status === "starting"
              ? "Starting: installing dependencies and building."
              : !buildPassed
                ? "This code version did not build, so there is nothing to run."
                : "Not running. Start it in Build to see the app before deciding."}
          </span>
        </span>
      </button>
    </li>
  );
}

function Evidence({
  ok,
  line,
  stage,
  onOpen,
}: {
  ok: boolean;
  line: string;
  stage: CodeStageId;
  onOpen: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full cursor-pointer items-start gap-2.5 rounded-xl border border-[color:var(--tp-line)] px-3.5 py-2.5 text-left transition-colors hover:border-blue-500/40"
      >
        {ok ? (
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
        ) : (
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
        )}
        <span className="min-w-0 flex-1">
          <span className={cn("block text-[13px] font-medium text-[color:var(--tp-ink)]")}>
            {CODE_STAGE_META[stage].label}
          </span>
          <span className="tp-den">{line}</span>
        </span>
      </button>
    </li>
  );
}
