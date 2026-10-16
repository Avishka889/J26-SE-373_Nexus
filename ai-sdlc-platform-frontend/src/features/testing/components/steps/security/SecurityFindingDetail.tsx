import { useState } from "react";
import { ArrowUpRight, Bot, Cpu, ShieldCheck, X } from "lucide-react";
import { Badge, Button } from "@/shared/ui/primitives";
import { Note } from "../../bits/index";
import { CodeDiff, UnifiedDiff } from "../../RepairProof";
import type { Finding } from "../../../fixtures/types";
import { atLine, type StepId } from "../../../model/view";

/** The two decisions that take a reason, in the words each asks for it with. */
const ASKS = {
  dismiss: {
    label: "Why this finding is dismissed",
    placeholder: "For example: the id is validated as a UUID before it reaches the query",
    send: "Dismiss with this reason",
  },
  accept: {
    label: "Why this can ship as it is",
    placeholder: "For example: the route sits behind the admin login until sprint 2",
    send: "Accept the risk with this reason",
  },
} as const;

export function SecurityFindingDetail({
  finding,
  shipsWith,
  applyBlocked,
  onApplyFix,
  onDismiss,
  onAccept,
  onGoTo,
}: {
  finding: Finding;
  /** What a fix applied now ships with, when that is newer code than may ship (C4-13). */
  shipsWith?: string | null;
  /** Why no fix can be applied yet, when another fix waits for its run (C3-9). */
  applyBlocked?: string | null;
  /** Resolves false when the server refused, so the detail can keep its state. */
  onApplyFix: (id: string) => Promise<boolean> | void;
  onDismiss: (id: string, reason: string) => Promise<boolean> | void;
  /**
   * Accept the risk of a real finding, with the reason it can ship as it is:
   * the release gate lets a Critical or High one through only so (G8).
   */
  onAccept: (id: string, reason: string) => Promise<boolean> | void;
  onGoTo: (step: StepId) => void;
}) {
  const proposal = finding.proposal;
  const undecided = finding.status === "open" || finding.status === "fix-proposed";
  // A fix someone accepted but that never reached the code can still be
  // applied; one that was dismissed or rolled back cannot.
  const canApply =
    undecided && (Boolean(finding.fix) || proposal?.state === "proposed" || proposal?.state === "accepted");

  // Which decision is asking for its reason, if any.
  const [deciding, setDeciding] = useState<"dismiss" | "accept" | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<"apply" | "dismiss" | "accept" | null>(null);

  const applyFix = async () => {
    setBusy("apply");
    try {
      await onApplyFix(finding.id);
    } finally {
      setBusy(null);
    }
  };

  // The reason is the record of why a weakness the detectors found does not
  // apply here, or why it can ship as it is, so the text stays until the server
  // has kept it.
  const decide = async () => {
    const why = reason.trim();
    if (!why || deciding === null) return;
    setBusy(deciding);
    try {
      const send = deciding === "dismiss" ? onDismiss : onAccept;
      if ((await send(finding.id, why)) === false) return;
      setReason("");
      setDeciding(null);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3.5">
      <div>
        <p className="tp-label">What the problem is</p>
        <Note className="mt-1.5 max-w-3xl">{finding.explanation}</Note>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="tp-label mr-1">Found by</span>
        {finding.foundBy.includes("local") && (
          <Badge variant="default">
            <Cpu className="h-3 w-3" />
            Local model
          </Badge>
        )}
        {finding.foundBy.includes("reviewer") && (
          <Badge variant="default">
            <Bot className="h-3 w-3" />
            AI reviewer
          </Badge>
        )}
        {finding.foundBy.length === 2 && <span className="tp-den">both detectors agreed on this one</span>}
        <span className="ml-auto font-mono text-[11px] text-[color:var(--tp-ink-2)]">
          {atLine(finding.file, finding.line)}
        </span>
      </div>

      {proposal ? (
        <div>
          <p className="tp-label">Proposed fix</p>
          <Note className="mb-1 mt-1.5">{proposal.summary}</Note>
          {proposal.risk && <p className="tp-den mb-2">{proposal.risk}</p>}
          <UnifiedDiff hunks={proposal.hunks} />
        </div>
      ) : finding.fix ? (
        <div>
          <p className="tp-label">Proposed fix</p>
          <Note className="mb-2 mt-1.5">{finding.fix.summary}</Note>
          <CodeDiff
            before={finding.fix.before}
            after={finding.fix.after}
            language={finding.fix.language}
            beforeLabel="Code today"
            afterLabel="Proposed fix"
          />
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-white p-3 dark:border-white/[0.06] dark:bg-white/[0.02]">
          <Note className="text-[12.5px]">
            {finding.openReason ??
              "No fix was proposed for this finding. If it does not apply to this project, dismiss it and say why."}
          </Note>
        </div>
      )}

      {canApply && shipsWith && <Note className="text-[12.5px]">{shipsWith}</Note>}
      {canApply && applyBlocked && <Note className="text-[12.5px]">{applyBlocked}</Note>}

      <div className="flex flex-wrap items-center gap-2 border-t border-[color:var(--tp-line)] pt-3.5">
        {canApply && (
          <Button
            variant="primary"
            size="sm"
            busy={busy === "apply"}
            disabled={busy !== null || Boolean(applyBlocked)}
            onClick={() => void applyFix()}
          >
            <ShieldCheck className="h-3.5 w-3.5" />
            Apply fix
          </Button>
        )}
        {undecided && deciding === null && (
          <Button variant="outline" size="sm" disabled={busy !== null} onClick={() => setDeciding("dismiss")}>
            <X className="h-3.5 w-3.5" />
            Dismiss
          </Button>
        )}
        {undecided && deciding === null && !finding.riskAccepted && (
          <Button variant="outline" size="sm" disabled={busy !== null} onClick={() => setDeciding("accept")}>
            Accept the risk
          </Button>
        )}
        {canApply && (
          <p className="tp-den ml-auto max-w-sm text-right">
            Applying writes the patch as a new code version. Run the tests again, then re-verify it under
            Remediation.
          </p>
        )}
        {finding.status === "fix-applied" && (
          <>
            <Note className="text-[12.5px]">
              {proposal?.appliedCodeVersion
                ? `Applied as code version ${proposal.appliedCodeVersion}. Run the tests again, then re-verify it.`
                : "Applied. Run the tests again, then re-verify it."}
            </Note>
            <button
              type="button"
              onClick={() => onGoTo("remediation")}
              className="inline-flex items-center gap-1.5 text-[13px] text-blue-600 underline underline-offset-2 dark:text-blue-400"
            >
              Re-verify under Remediation
              <ArrowUpRight className="h-3.5 w-3.5" />
            </button>
          </>
        )}
        {(finding.status === "re-verifying" || finding.status === "verified") && (
          <button
            type="button"
            onClick={() => onGoTo("remediation")}
            className="inline-flex items-center gap-1.5 text-[13px] text-blue-600 underline underline-offset-2 dark:text-blue-400"
          >
            {finding.status === "verified" ? "See both proofs" : "Watch the proofs run"}
            <ArrowUpRight className="h-3.5 w-3.5" />
          </button>
        )}
        {finding.status === "dismissed" && <Note className="text-[12.5px]">Dismissed. It stays in the audit log.</Note>}
        {finding.riskAccepted && (
          <Note className="text-[12.5px]">Risk accepted: {finding.riskAccepted}</Note>
        )}
      </div>

      {undecided && deciding !== null && (
        <div className="space-y-2">
          <label className="block" htmlFor={`${deciding}-${finding.id}`}>
            <span className="tp-label">{ASKS[deciding].label}</span>
            <textarea
              id={`${deciding}-${finding.id}`}
              rows={2}
              value={reason}
              autoFocus
              onChange={(event) => setReason(event.target.value)}
              placeholder={ASKS[deciding].placeholder}
              className="mt-1 w-full resize-none rounded-xl border border-[color:var(--tp-line-strong)] bg-transparent px-3 py-2 text-[13px] outline-none focus:border-blue-500/50"
            />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              busy={busy === deciding}
              disabled={!reason.trim() || busy !== null}
              onClick={() => void decide()}
            >
              {ASKS[deciding].send}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy !== null}
              onClick={() => {
                setDeciding(null);
                setReason("");
              }}
            >
              Cancel
            </Button>
            <p className="tp-den">The reason is kept in the audit log beside the finding.</p>
          </div>
        </div>
      )}
    </div>
  );
}
