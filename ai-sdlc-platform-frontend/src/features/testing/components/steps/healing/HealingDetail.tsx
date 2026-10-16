import { useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  Bug,
  Check,
  PauseCircle,
  PencilLine,
  RotateCcw,
  ShieldAlert,
  Wrench,
  X,
} from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { Badge, Button } from "@/shared/ui/primitives";
import { Note, Panel, StateChip, TriageChip } from "../../bits/index";
import { RepairProof } from "../../RepairProof";
import { atLine, fileName, type ViewFailure } from "../../../model/view";
import { formatWhen } from "@/shared/utils/time";

export function HealingDetail({
  failure,
  showDetail,
  onBack,
  onApprove,
  onReject,
  onDecideTest,
  onOpenFile,
  onOpenCode,
}: {
  failure: ViewFailure;
  showDetail: boolean;
  onBack: () => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  /** Quarantine a failing test, restore one, or ask for one written again. */
  onDecideTest?: (
    id: string,
    decision: "quarantined" | "restored" | "rewrite",
    note?: string,
  ) => Promise<unknown>;
  onOpenFile: (path: string, line: number, label: string) => void;
  /** Where a regression goes: the code is what has to change, not the test. */
  onOpenCode: () => void;
}) {
  const guardBlocked = failure.state === "blocked";
  // Offered until a decision is in: once the server has one, it is shown instead.
  const decidable =
    failure.state === "awaiting-approval" && Boolean(failure.repair) && !failure.decision;
  const kept = failure.decision?.decision === "approved";
  const label = failure.label;
  const protects =
    failure.requirements && failure.requirements.length > 0
      ? failure.requirements.join(", ")
      : failure.requirement.id;

  return (
    <div className={cn("min-w-0 space-y-3", !showDetail && "hidden lg:block")}>
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-1.5 text-[13px] font-medium text-blue-600 lg:hidden dark:text-blue-400"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to the inbox
      </button>
      <Panel
        icon={<Wrench className="h-4 w-4 text-blue-400" />}
        label={`Failure · ${fileName(failure.moduleId)}`}
        meta={[protects && `protects ${protects}`, failure.runner, formatWhen(failure.at)]
          .filter(Boolean)
          .join(" · ")}
        action={
          <div className="flex flex-wrap items-center gap-1.5">
            <TriageChip failure={failure} />
            <StateChip failure={failure} />
          </div>
        }
      >
        <div className="space-y-4">
          {/* The test by its reference and its story, in the page's own type.
              It was the whole name in monospace, broken wherever the line
              ran out: "spec / ialty", "recept / ionist". */}
          <div>
            <h4 className="break-words text-[14px] font-semibold leading-snug text-[color:var(--tp-ink)]">
              {label?.ref ? (
                <>
                  <span className="font-mono text-[13px]">{label.ref}</span>
                  {label.story && <span className="font-medium"> · {label.story}</span>}
                </>
              ) : (
                failure.test
              )}
            </h4>
            {label?.ref && label.text && <Note className="mt-1.5">{label.text}</Note>}
          </div>

          {/* What the runner said. A first run had only "nothing to compare
              with" here, and its failures were decided without knowing why
              they failed. */}
          {failure.message && (
            <div>
              <p className="tp-label">Why it failed</p>
              <p className="mt-1.5 break-words rounded-lg border border-red-500/25 bg-red-500/5 px-3 py-2 font-mono text-[12px] leading-relaxed text-[color:var(--tp-ink)]">
                {failure.message}
              </p>
            </div>
          )}

          <div>
            <p className="tp-label">{failure.triage === "unclassified" ? "Why it is not classified" : "How it was classified"}</p>
            <Note className="mt-1.5">{failure.reason}</Note>
          </div>

          <button
            type="button"
            onClick={() => onOpenFile(failure.file, failure.line, failure.message || failure.reason)}
            className="group inline-flex flex-wrap items-center gap-1.5 font-mono text-[11.5px] text-blue-600 dark:text-blue-400"
          >
            <span className="underline underline-offset-2 group-hover:decoration-2">
              {atLine(fileName(failure.file), failure.line)}
            </span>
            <ArrowUpRight className="h-3 w-3" />
            <span className="tp-den">
              {failure.line > 0 ? "open the test file at the failing line" : "open the test file"}
            </span>
          </button>

          {failure.decision && (
            <div
              className={cn(
                "flex items-start gap-2.5 rounded-lg border p-3",
                failure.decision.decision === "approved"
                  ? "border-emerald-500/30 bg-emerald-500/5"
                  : "border-slate-200 bg-slate-50 dark:border-white/[0.06] dark:bg-white/[0.02]"
              )}
            >
              {kept ? (
                <Check className="mt-px h-4 w-4 shrink-0 text-emerald-500" />
              ) : (
                <X className="mt-px h-4 w-4 shrink-0 text-slate-400" />
              )}
              <div className="min-w-0 flex-1 space-y-2">
                <p className="text-[13px] leading-snug">
                  {failure.decision.by} {kept ? "kept" : "rejected"} this repair at{" "}
                  {formatWhen(failure.decision.at)}.{" "}
                  {kept
                    ? "The test file now carries it. This run measured the test before the repair: request changes at the review to run the tests with it."
                    : "The test stays as written."}{" "}
                  It is in the audit log and in the report.
                </p>
                {kept && (
                  <Button variant="outline" size="sm" onClick={() => onReject(failure.id)}>
                    <X className="h-3.5 w-3.5" />
                    Put the test back
                  </Button>
                )}
              </div>
            </div>
          )}

          {failure.repair && <RepairProof repair={failure.repair} />}

          {failure.repair && (
            <div>
              <p className="tp-label">Why the test was stale</p>
              <Note className="mt-1.5">{failure.repair.why}</Note>
            </div>
          )}

          {!failure.repair && failure.note && (
            <div>
              <p className="tp-label">{failure.triage === "regression" ? "What broke" : "What happened"}</p>
              <Note className="mt-1.5">{failure.note}</Note>
            </div>
          )}

          {failure.repair && failure.note && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-white/[0.06] dark:bg-white/[0.02]">
              <Note className="text-[12.5px]">{failure.note}</Note>
            </div>
          )}

          {decidable && (
            <div className="flex flex-wrap items-center gap-2 border-t border-[color:var(--tp-line)] pt-4">
              {/* Not offered for an API test: the server refuses it, and says why below. */}
              {!failure.rewrittenEachRun && (
                <Button variant="primary" size="sm" onClick={() => onApprove(failure.id)}>
                  <Check className="h-3.5 w-3.5" />
                  Keep the repair
                </Button>
              )}
              <Button variant="outline" size="sm" onClick={() => onReject(failure.id)}>
                <X className="h-3.5 w-3.5" />
                Reject it
              </Button>
              <p className="tp-den ml-auto">
                {failure.rewrittenEachRun
                  ? "This is an API test, which every run writes again from the contract, so a repair to it would not last. Its failure means the code does not answer as the contract says: change the code, or the contract."
                  : "Keeping it writes the repair into the test file, which the next run and Deployment's staging build run. Rejecting it leaves the test as written."}
              </p>
            </div>
          )}

          {guardBlocked && (
            <div className="flex items-start gap-2.5 rounded-lg border border-red-500/30 bg-red-500/5 p-3">
              <ShieldAlert className="mt-px h-4 w-4 shrink-0 text-red-500 dark:text-red-400" />
              <p className="text-[13px] leading-snug">
                There is nothing to approve here. The guard rejected this repair, so the test stays as
                written and the failure stays open
                {failure.owner ? `, with ${failure.owner}` : ""}. The rejected proposal is above for
                whoever fixes it.
              </p>
            </div>
          )}

          {/* A kept repair is already in the test file, for the next run to measure. */}
          {onDecideTest &&
            failure.state !== "healed" &&
            !failure.awaitingRerun &&
            failure.decision?.decision !== "approved" && (
              <SetAsideControls failure={failure} onDecideTest={onDecideTest} />
            )}

          {/* A first run cannot say which of the two is wrong, and offered only
              what to do when it is the test. */}
          {failure.triage === "unclassified" && failure.state !== "quarantined" && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-[color:var(--tp-line)] pt-4">
              <p className="tp-den min-w-0 flex-1 basis-64">
                If the test is right, the code has to change, and nothing on this page repairs code.
                Generate it again in Code Generation, or correct the requirement in Requirements &amp;
                Design if the rule is missing there.
              </p>
              <Button size="sm" variant="outline" onClick={onOpenCode}>
                <ArrowUpRight className="h-3.5 w-3.5" />
                Open Code Generation
              </Button>
            </div>
          )}

          {failure.triage === "regression" && (
            <div className="flex flex-wrap items-center gap-2 border-t border-[color:var(--tp-line)] pt-4">
              <Badge variant="error">
                <Bug className="h-3 w-3" />
                A regression in the code
              </Badge>
              <p className="tp-den min-w-0 flex-1">
                Never repaired automatically: the test stays as written, and the code has to change. Ask
                for that in Code Generation; requesting changes here rewrites tests that fail again.
              </p>
              <Button size="sm" variant="outline" onClick={onOpenCode}>
                <ArrowUpRight className="h-3.5 w-3.5" />
                Open Code Generation
              </Button>
            </div>
          )}
        </div>
      </Panel>
    </div>
  );
}

/**
 * What a person can do with a failing generated test no repair will fix.
 *
 * The test review is not approved while a generated test fails, so one wrong
 * test written by the model made a project unreleasable. Quarantining it with a
 * reason, or sending a test that never passed back to be written again, are the
 * two ways on, and the server keeps both in the test file and in Activity.
 */
function SetAsideControls({
  failure,
  onDecideTest,
}: {
  failure: ViewFailure;
  onDecideTest: (
    id: string,
    decision: "quarantined" | "restored" | "rewrite",
    note?: string,
  ) => Promise<unknown>;
}) {
  const [asking, setAsking] = useState<"quarantined" | "rewrite" | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const aside = failure.setAside;

  const send = async (decision: "quarantined" | "restored" | "rewrite", note?: string) => {
    setBusy(true);
    try {
      // A refusal answers nothing and is said by the page, and the reason
      // typed here stays for another try.
      if (await onDecideTest(failure.id, decision, note)) {
        setAsking(null);
        setReason("");
      }
    } finally {
      setBusy(false);
    }
  };

  if (aside) {
    const quarantined = aside.decision === "quarantined";
    return (
      <div className="flex items-start gap-2.5 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
        {quarantined ? (
          <PauseCircle className="mt-px h-4 w-4 shrink-0 text-amber-500" />
        ) : (
          <PencilLine className="mt-px h-4 w-4 shrink-0 text-amber-500" />
        )}
        <div className="min-w-0 flex-1 space-y-2">
          <p className="text-[13px] leading-snug">
            {quarantined
              ? `${aside.by} quarantined this test at ${formatWhen(aside.at)}: ${aside.note}. It is skipped in the next run and in Deployment's staging build, with that reason above it in the test file, until it is restored. The review no longer waits on it.`
              : `${aside.by} asked for this test to be written again at ${formatWhen(aside.at)}: ${aside.note}. It is back to a todo in the test file, so the next run writes it afresh: request changes at the review to run the tests again.`}
          </p>
          {quarantined && (
            <Button variant="outline" size="sm" busy={busy} onClick={() => void send("restored")}>
              <RotateCcw className="h-3.5 w-3.5" />
              Restore the test
            </Button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2 border-t border-[color:var(--tp-line)] pt-4">
      {asking === null ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setAsking("quarantined")}>
            <PauseCircle className="h-3.5 w-3.5" />
            Quarantine with a reason
          </Button>
          {/* An API test is written from the contract on every run, so asking for it again changes nothing. */}
          {!failure.rewrittenEachRun && (
            <Button variant="outline" size="sm" onClick={() => setAsking("rewrite")}>
              <PencilLine className="h-3.5 w-3.5" />
              Write it again
            </Button>
          )}
          {/* A line of its own. Beside the buttons it was a sliver two words
              wide whenever the conversation was open. */}
          <p className="tp-den basis-full">
            When the test, not the code, is wrong. Quarantining skips it, with your reason in the test
            file, until it is restored. Writing it again is for a test that never passed: the next run
            writes it afresh from its acceptance criterion.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          <label className="block" htmlFor={`aside-${failure.id}`}>
            <span className="tp-label">
              {asking === "quarantined" ? "Why this test is quarantined" : "What is wrong with this test"}
            </span>
            <textarea
              id={`aside-${failure.id}`}
              rows={2}
              value={reason}
              autoFocus
              onChange={(event) => setReason(event.target.value)}
              placeholder={
                asking === "quarantined"
                  ? "For example: it asserts a title the design no longer has"
                  : "For example: it checks the total before the discount is applied"
              }
              className="mt-1 w-full resize-none rounded-xl border border-[color:var(--tp-line-strong)] bg-transparent px-3 py-2 text-[13px] outline-none focus:border-blue-500/50"
            />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              busy={busy}
              disabled={!reason.trim()}
              onClick={() => void send(asking, reason.trim())}
            >
              {asking === "quarantined" ? "Quarantine it" : "Ask for it again"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => {
                setAsking(null);
                setReason("");
              }}
            >
              Cancel
            </Button>
            <p className="tp-den">The reason is kept in the test file and in Activity.</p>
          </div>
        </div>
      )}
    </div>
  );
}
