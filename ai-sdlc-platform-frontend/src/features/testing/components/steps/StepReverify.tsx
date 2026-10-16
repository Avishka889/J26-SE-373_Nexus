import { AlertTriangle, ArrowUpRight, RefreshCw, ShieldCheck } from "lucide-react";
import { Button } from "@/shared/ui/primitives";
import { Note, Panel, SeverityChip } from "../bits/index";
import { ProofPair } from "../ProofPair";
import type { StepId, TestingView } from "../../model/view";
import { atLine, shortPath } from "../../model/view";
import { formatWhen } from "@/shared/utils/time";

export function StepReverify({
  view,
  onGoTo,
  onRetry,
  onReverify,
}: {
  view: TestingView;
  onGoTo: (step: StepId) => void;
  onRetry: (findingId: string) => void;
  onReverify: (findingId: string) => void;
}) {
  // No finding, so nothing to fix: the stage said "No fix has been applied
  // yet" and offered the findings table, as if one were owed.
  if (view.fixes.length === 0 && view.findings.length === 0) {
    return (
      <Panel
        icon={<ShieldCheck className="h-4 w-4 text-emerald-500" />}
        label="Fix and re-verify"
        title="Nothing to remediate"
      >
        <Note className="max-w-2xl">
          The scan raised no findings at test version {view.build}, so no fix was proposed and there
          is nothing to re-verify.
        </Note>
      </Panel>
    );
  }

  if (view.fixes.length === 0) {
    return (
      <Panel
        icon={<ShieldCheck className="h-4 w-4 text-blue-400" />}
        label="Fix and re-verify"
        title="No fix has been applied yet"
      >
        <Note className="max-w-2xl">
          When you apply a fix in the findings table, two proofs start here: the scanner runs again to show the issue is
          gone, and the whole suite runs again to show behaviour did not change. A fix only reads as fixed when both
          pass.
        </Note>
        <Button variant="outline" size="sm" className="mt-3" onClick={() => onGoTo("security-scan")}>
          Go to the findings
          <ArrowUpRight className="h-3.5 w-3.5" />
        </Button>
      </Panel>
    );
  }

  return (
    <div className="space-y-4">
      {view.fixes.some((f) => f.scan.state === "errored" || f.suite.state === "errored") ? (
        <div className="flex items-start gap-2.5 rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3">
          <AlertTriangle className="mt-px h-4 w-4 shrink-0 text-amber-500 dark:text-amber-400" />
          <Note className="max-w-3xl text-[12.5px]">
            A proof could not answer. That is not a pass and not a fail - it means nothing was proven, so the finding
            stays unresolved until you retry it.
          </Note>
        </div>
      ) : (
        <div className="flex items-start gap-2.5 rounded-lg border border-blue-500/30 bg-blue-500/5 px-4 py-3">
          <ShieldCheck className="mt-px h-4 w-4 shrink-0 text-blue-400" />
          <Note className="max-w-3xl text-[12.5px]">
            Every applied fix has to clear two proofs: the scan runs again on the whole codebase, and the suite runs
            again against the pre-fix result. Both have to pass. One passing proof is not a fixed finding.
          </Note>
        </div>
      )}

      {view.fixes.map((fix) => {
        const finding = view.findings.find((f) => f.id === fix.findingId);
        if (!finding) return null;
        const both = fix.scan.state === "pass" && fix.suite.state === "pass";
        const broken = fix.scan.state === "errored" || fix.suite.state === "errored";
        const inFlight = fix.scan.state === "running" || fix.suite.state === "running";
        // Nothing has been proven yet. The proof is a subtraction over two runs, so it needs a
        // run against the version carrying the fix, and asking before that happens is answered
        // with what to do instead.
        const unproven = fix.scan.state === "pending";

        return (
          <Panel
            key={fix.findingId}
            icon={<ShieldCheck className="h-4 w-4 text-blue-400" />}
            label={`${finding.cwe} · ${atLine(shortPath(finding.file), finding.line)}`}
            title={finding.name}
            meta={`Applied by ${fix.appliedBy} at ${formatWhen(fix.appliedAt)}`}
            action={<SeverityChip severity={finding.severity} />}
          >
            <ProofPair
              label="Two proofs"
              meta={both ? "both passed" : "green only when both pass"}
              left={{ label: "Scan again", state: fix.scan.state, detail: fix.scan.detail, at: fix.scan.at }}
              right={{ label: "Suite re-run", state: fix.suite.state, detail: fix.suite.detail, at: fix.suite.at }}
              verdict={{
                state: both
                  ? "pass"
                  : fix.suite.state === "fail" || fix.scan.state === "fail"
                  ? "fail"
                  : broken
                  ? "errored"
                  : "running",
                text: fix.verdict,
              }}
              footer={
                broken ? (
                  <div className="flex flex-wrap items-center gap-3">
                    <Button variant="outline" size="sm" onClick={() => onRetry(fix.findingId)}>
                      <RefreshCw className="h-3.5 w-3.5" />
                      Retry both proofs
                    </Button>
                    <Note className="text-[12.5px]">
                      Nothing was proven, so the fix still counts as unresolved. The code change is untouched.
                    </Note>
                  </div>
                ) : unproven ? (
                  <div className="flex flex-wrap items-center gap-3">
                    <Button variant="outline" size="sm" onClick={() => onReverify(fix.findingId)}>
                      <RefreshCw className="h-3.5 w-3.5" />
                      Re-verify now
                    </Button>
                    <Note className="text-[12.5px]">
                      {fix.pendingNote ??
                        "The proofs compare this run against the one before the fix, so the tests have to run once against the version carrying it."}
                    </Note>
                  </div>
                ) : inFlight ? (
                  <div className="flex flex-wrap items-center gap-3">
                    <Button variant="outline" size="sm" onClick={() => onRetry(fix.findingId)}>
                      <RefreshCw className="h-3.5 w-3.5" />
                      Start again
                    </Button>
                    <Note className="text-[12.5px]">
                      If a proof has not answered in a few minutes, start it again - the runner may have dropped the job.
                    </Note>
                  </div>
                ) : undefined
              }
            />
          </Panel>
        );
      })}
    </div>
  );
}
