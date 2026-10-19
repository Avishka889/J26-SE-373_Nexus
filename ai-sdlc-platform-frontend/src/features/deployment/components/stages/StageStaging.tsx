import { useState } from "react";
import { ArrowUpRight, FlaskRound, RefreshCw } from "lucide-react";
import { Button } from "@/shared/ui/primitives";
import { Console } from "@/shared/ui/console";
import { Chip, Panel } from "@/shared/ui/phase";
import { StageSection } from "@/shared/ui/stage";
import type { DeploySnapshot } from "../../api/types";
import type { DeploymentPageView } from "../../model/view";
import { shortHash } from "../../model/view";
import { EmptyNote, Facts, Mono, StateChip } from "../bits";

/**
 * Staging Verification: the candidate built, started and checked like production.
 *
 * Verified is computed, not claimed: every step passed, the image has a
 * digest, the running container served its own fingerprint, and every smoke
 * request answered. The console is the steps' real output, as the code and
 * testing phases show theirs.
 */
export function StageStaging({
  snapshot,
  view,
  onRetry,
  onOpenTesting,
}: {
  snapshot: DeploySnapshot;
  view: DeploymentPageView;
  /** Stage the same candidate again; may resolve when the server has answered. */
  onRetry: () => void | Promise<unknown>;
  onOpenTesting: () => void;
}) {
  const candidate = snapshot.candidate;
  if (!candidate) return <EmptyNote>No release candidate has been built at this deploy version.</EmptyNote>;
  const fingerprintMatches = candidate.fingerprint === candidate.candidateHash;
  const failedStep = candidate.steps.find((step) => step.outcome === "failed")?.name ?? null;

  return (
    <div className="space-y-4">
      {/* Try again belongs to a stage that failed, and this one finished: its
          outcome is a candidate that did not verify. While the review waits
          that left only Request changes, which runs every stage again. */}
      {!candidate.verified && view.decisionPending && (
        <RetryStaging failedStep={failedStep} onRetry={onRetry} onOpenTesting={onOpenTesting} />
      )}
      <StageSection id="staging-steps">
        <Panel
          icon={<FlaskRound className="h-4 w-4 text-blue-400" />}
          label="Verification steps"
          title={
            candidate.verified
              ? "Verified: the candidate built, served its own fingerprint and answered every smoke request."
              : "Not verified: the release guards will refuse to ship it."
          }
          action={<StateChip state={candidate.verified ? "passed" : "failed"} />}
        >
          <Facts
            rows={[
              ["Candidate", <Mono key="hash">{shortHash(candidate.candidateHash)}</Mono>],
              ["Image", candidate.image ? <Mono key="image">{candidate.image}</Mono> : "none"],
              ["Image digest", <Mono key="digest">{shortHash(candidate.imageDigest)}</Mono>],
              [
                "Fingerprint served",
                fingerprintMatches ? "matches the candidate" : `served ${shortHash(candidate.fingerprint)}`,
              ],
              ["Toolchain", candidate.toolchain],
              ["Isolation", candidate.isolation],
              [
                "Updates included",
                `${candidate.included.length}` +
                  (candidate.excluded.length ? `, ${candidate.excluded.length} left out` : ""),
              ],
            ]}
          />
          <ul className="mt-4 divide-y divide-[color:var(--tp-line)]">
            {candidate.steps.map((step) => (
              <li key={step.name} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                <span className="text-[13px] font-medium">{step.name}</span>
                <Mono className="min-w-0 flex-1 basis-48 text-[color:var(--tp-ink-2)]">{step.command}</Mono>
                <StateChip state={step.outcome} />
                {step.durationSeconds !== null && step.durationSeconds !== undefined && (
                  <span className="tp-den">{step.durationSeconds.toFixed(1)} s</span>
                )}
              </li>
            ))}
          </ul>
          <p className="tp-label mt-4">Smoke requests</p>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {candidate.smoke.map((check) => (
              <li key={check.path}>
                <Chip tone={check.ok ? "pass" : "fail"} title={check.detail}>
                  {check.method} {check.path} {check.statusCode ?? "no answer"}
                </Chip>
              </li>
            ))}
          </ul>
          {candidate.excluded.length > 0 && (
            <ul className="mt-3 space-y-1">
              {candidate.excluded.map((one) => (
                <li key={one.updateId} className="tp-den break-words">
                  Left out ({one.reason}): {one.detail}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </StageSection>

      <StageSection id="staging-console">
        {/* Bounded like Testing's run transcript, so a long build log scrolls
            inside the console instead of stretching the stage (3,053px live). */}
        <Console
          className="max-h-[300px] sm:max-h-[420px]"
          lines={view.stagingTranscript}
          label="Staging transcript"
          meta="What each staging step printed, in order"
        />
      </StageSection>
    </div>
  );
}

function RetryStaging({
  failedStep,
  onRetry,
  onOpenTesting,
}: {
  failedStep: string | null;
  onRetry: () => void | Promise<unknown>;
  onOpenTesting: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const retry = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await onRetry();
    } catch {
      // Reported by the page; the button only has to be offered again.
    } finally {
      setBusy(false);
    }
  };
  const testsFailed = failedStep === "test";

  return (
    <section className="rounded-xl border border-red-500/30 bg-red-500/5 px-3.5 py-3 text-[13px]">
      <p className="font-semibold text-[color:var(--tp-ink)]">
        {failedStep ? `Staging stopped at the ${failedStep} step` : "This candidate was not verified"}
      </p>
      <p className="mt-1 text-[color:var(--tp-ink-2)]">
        {testsFailed
          ? "The project's tests failed inside the candidate. Fix them in Testing, or stage again if the failure was the machine rather than the tests."
          : "Staging again builds and checks the same candidate at this deploy version. Nothing else is regenerated, and the release review waits on the result."}
      </p>
      <div className="mt-2.5 flex flex-wrap gap-2">
        <Button variant="primary" size="sm" busy={busy} onClick={() => void retry()}>
          <RefreshCw className="h-3.5 w-3.5" />
          Retry staging
        </Button>
        {testsFailed && (
          <Button variant="outline" size="sm" onClick={onOpenTesting}>
            <ArrowUpRight className="h-3.5 w-3.5" />
            Open Testing
          </Button>
        )}
      </div>
    </section>
  );
}
