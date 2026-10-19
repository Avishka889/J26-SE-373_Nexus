import { useState, type ReactNode } from "react";
import { useDraft } from "@/shared/hooks";
import { AlertOctagon, History, Rocket, RotateCcw } from "lucide-react";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { Button, Table, Td, Th } from "@/shared/ui/primitives";
import { Console } from "@/shared/ui/console";
import { Chip, Note, Panel } from "@/shared/ui/phase";
import { StageSection } from "@/shared/ui/stage";
import type { DeploymentView, RollbackDecisionInput } from "../../api/types";
import type { DeploymentPageView } from "../../model/view";
import { shortHash } from "../../model/view";
import { Address, EmptyNote, Facts, Mono, StateChip } from "../bits";
import { formatWhen } from "@/shared/utils/time";

/** A recorded cause as a sentence: capitalised and closed, whatever the provider sent. */
function sentence(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return "";
  const capital = trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(capital) ? capital : `${capital}.`;
}

/**
 * The decision FR20 reserves for a person: roll a release back, or not.
 *
 * Nothing on this page, and nothing on the server, starts a rollback without
 * it. Declining is a decision too, and it carries its reason.
 */
function RollbackDecision({
  release,
  what,
  restoresTo,
  cannotRestore,
  dataNote,
  busy,
  isDark,
  onDecide,
  draftKey,
}: {
  release: DeploymentView;
  what: string;
  restoresTo: number | null;
  cannotRestore: string;
  /** What a restore does to the data: the decision was made without it. */
  dataNote: string;
  busy: boolean;
  isDark: boolean;
  onDecide: (decision: RollbackDecisionInput["decision"], note: string) => Promise<boolean>;
  /** Where the note's draft is kept, so it survives the stage being closed. */
  draftKey: string;
}) {
  const [note, setNote] = useDraft(draftKey);
  const [confirming, setConfirming] = useState(false);
  const decide = async (decision: RollbackDecisionInput["decision"]) => {
    if (await onDecide(decision, note)) setNote("");
  };
  // Held when the server would refuse, saying why: both were enabled only to
  // be refused.
  const noReason = note.trim() === "";
  return (
    <section
      data-rollback-decision
      className="overflow-hidden rounded-2xl border border-red-500/40 bg-red-500/5"
    >
      <div className="flex flex-wrap items-start gap-3 px-4 py-3.5">
        <AlertOctagon className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold text-[color:var(--tp-ink)]">
            Deploy version {release.deployVersion} {what}, and a rollback waits for your decision
          </p>
          <Note className="mt-1 break-words text-[12.5px]">
            {sentence(release.cause) || "It stopped serving what was released."}
            {release.faultInjected
              ? ` This was a controlled failure (${release.faultInjected}), injected to exercise the rollback path.`
              : ""}{" "}
            {restoresTo !== null
              ? `Approving restores deploy version ${restoresTo}, the last verified release, and reports it restored only when that release's fingerprint is served again.`
              : `There is nothing to restore: ${cannotRestore}.`}
            {restoresTo !== null && dataNote ? ` ${dataNote}` : ""}
          </Note>
          <label className="mt-2 block" htmlFor="rollback-note">
            <span className="tp-label">Note, required to decline</span>
            <textarea
              id="rollback-note"
              rows={2}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Why, if you are not rolling it back"
              className="mt-1 w-full resize-none rounded-xl border border-[color:var(--tp-line-strong)] bg-transparent px-3 py-2 text-[13px] outline-none focus:border-blue-500/50"
            />
          </label>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              variant="error"
              size="sm"
              busy={busy}
              disabled={restoresTo === null}
              title={restoresTo === null ? `There is nothing to restore: ${cannotRestore}` : undefined}
              onClick={() => setConfirming(true)}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Approve the rollback
            </Button>
            <Button
              variant="outline"
              size="sm"
              busy={busy}
              disabled={noReason}
              title={noReason ? "Write why you are not rolling it back first" : undefined}
              onClick={() => void decide("rejected")}
            >
              Decline
            </Button>
          </div>
        </div>
      </div>
      {confirming && restoresTo !== null && (
        <ConfirmDialog
          title={`Roll back to deploy version ${restoresTo}?`}
          body={
            `Deploy version ${release.deployVersion} stops serving and deploy version ${restoresTo}, ` +
            "the last verified release, is started again. It is reported restored only when its " +
            `fingerprint is served.${dataNote ? ` ${dataNote}` : ""}`
          }
          confirmLabel="Approve the rollback"
          isDark={isDark}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            void decide("approved");
          }}
        />
      )}
    </section>
  );
}

function DeploymentCard({
  deployment,
  cloudApi,
}: {
  deployment: DeploymentView;
  /** A cloud release's API address, which the release record does not carry. */
  cloudApi: string | null;
}) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-semibold">
          {deployment.kind === "rollback" ? "Rollback" : "Release"} of deploy version{" "}
          {deployment.deployVersion}
        </span>
        <StateChip state={deployment.state} />
        {deployment.verified && <Chip tone="pass">verified</Chip>}
        {deployment.faultInjected && <Chip tone="caution">controlled failure: {deployment.faultInjected}</Chip>}
      </div>
      <Facts
        rows={[
          ["Target", deployment.target === "local" ? "This machine, in containers" : "Vercel and Render"],
          ["Candidate", <Mono key="c">{shortHash(deployment.candidateHash)}</Mono>],
          ["Requested by", deployment.requestedBy],
          ["Authorised by", deployment.authorisedBy || "not recorded"],
          ["Started", formatWhen(deployment.createdAt)],
          ["Finished", deployment.finishedAt ? formatWhen(deployment.finishedAt) : "still running"],
          ["Serves at", deployment.url ? <Address key="u" href={deployment.url} /> : "not yet"],
          ...(deployment.target === "cloud" && cloudApi
            ? ([["API at", <Address key="a" href={cloudApi} />]] as [string, ReactNode][])
            : []),
          ["Cause", deployment.cause || "none recorded"],
        ]}
      />
      <ol className="divide-y divide-[color:var(--tp-line)]">
        {deployment.steps.map((step) => (
          <li key={step.seq} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
            <span className="tp-label shrink-0">{String(step.seq + 1).padStart(2, "0")}</span>
            <span className="min-w-0 flex-1 basis-48 text-[13px]">{step.label}</span>
            {step.movesTraffic && <Chip tone="caution">moves traffic</Chip>}
            <StateChip state={step.state} />
          </li>
        ))}
      </ol>
    </div>
  );
}

/**
 * Production Release: what the orchestrator carried out after the review.
 *
 * Every attempt is on the ledger with its cause, the failed ones included
 * (FR16). A failure before traffic moved is compensated automatically; after
 * it moved, the release waits on a person's rollback decision (FR20).
 */
export function StageRelease({
  view,
  busy,
  isDark,
  onDecideRollback,
  onReleaseAgain,
  onLoadHistory,
}: {
  view: DeploymentPageView;
  busy: boolean;
  isDark: boolean;
  /** Every attempt beyond the newest ten, or null when it could not be read. */
  onLoadHistory: () => Promise<DeploymentView[] | null>;
  onDecideRollback: (
    deploymentId: string,
    decision: RollbackDecisionInput["decision"],
    note: string,
  ) => Promise<boolean>;
  /** Release the same approved version again; may resolve when the server has answered. */
  onReleaseAgain: (deploymentId: string) => void | Promise<unknown>;
}) {
  const release = view.release;
  const shown = release.active ?? release.history[0] ?? null;
  // The panel said "every release and rollback" over the newest ten.
  const [everything, setEverything] = useState<DeploymentView[] | null>(null);
  const [loading, setLoading] = useState(false);
  const listed = everything ?? release.history;
  const more = release.historyTotal > listed.length;
  // Undone before any traffic moved: nothing reached production, so the same
  // approved version may go again. After traffic moved it is a rollback instead.
  const undone = !release.active && shown?.kind === "release" && shown.state === "compensated" ? shown : null;

  return (
    <div className="space-y-4">
      {release.awaitingRollback && (
        <RollbackDecision
          release={release.awaitingRollback}
          what={release.awaitingWhat}
          restoresTo={release.restoresTo}
          cannotRestore={release.cannotRestore}
          dataNote={release.dataNote}
          busy={busy}
          isDark={isDark}
          onDecide={(decision, note) =>
            onDecideRollback(release.awaitingRollback!.id, decision, note)
          }
          draftKey={`${view.projectId}:rollback:${release.awaitingRollback.id}`}
        />
      )}

      <StageSection id="release-deployment">
        <Panel
          icon={<Rocket className="h-4 w-4 text-blue-400" />}
          label="Deployment"
          title={
            release.serving
              ? `Serving now: deploy version ${release.serving.deployVersion}, verified ${formatWhen(release.serving.verifiedAt)}.`
              : "Nothing verified serves yet."
          }
        >
          {undone && <ReleaseAgain onReleaseAgain={() => onReleaseAgain(undone.id)} busy={busy} />}
          {shown ? (
            <DeploymentCard deployment={shown} cloudApi={release.cloudApi} />
          ) : (
            <EmptyNote>Nothing has been released. A release starts when the review is approved.</EmptyNote>
          )}
        </Panel>
      </StageSection>

      <StageSection id="release-console">
        {/* Bounded like Testing's run transcript: a release's steps log a lot. */}
        <Console
          className="max-h-[300px] sm:max-h-[420px]"
          lines={view.releaseTranscript}
          streaming={view.releasing}
          label="Release transcript"
          meta={shown ? `${shown.kind} of deploy version ${shown.deployVersion}` : undefined}
        />
      </StageSection>

      <StageSection id="release-history">
        <Panel
          icon={<History className="h-4 w-4 text-blue-400" />}
          label="History"
          title={
            more
              ? `The newest ${listed.length} of ${release.historyTotal} releases and rollbacks, whatever came of them.`
              : "Every release and rollback, newest first, whatever came of it."
          }
          action={
            more ? (
              <Button
                variant="outline"
                size="sm"
                busy={loading}
                onClick={async () => {
                  setLoading(true);
                  try {
                    const found = await onLoadHistory();
                    if (found) setEverything(found);
                  } finally {
                    setLoading(false);
                  }
                }}
              >
                Show all {release.historyTotal}
              </Button>
            ) : undefined
          }
        >
          {listed.length === 0 ? (
            <EmptyNote>No attempt yet.</EmptyNote>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Attempt</Th>
                  <Th>State</Th>
                  <Th>Started</Th>
                  <Th>Authorised by</Th>
                </tr>
              </thead>
              <tbody>
                {listed.map((one) => (
                  <tr key={one.id}>
                    <Td>
                      {one.kind === "rollback" ? "Rollback to" : "Release of"} deploy version{" "}
                      {one.deployVersion}
                    </Td>
                    <Td>
                      <StateChip state={one.state} />
                    </Td>
                    <Td>{formatWhen(one.createdAt)}</Td>
                    <Td>{one.authorisedBy || one.requestedBy}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Panel>
      </StageSection>
    </div>
  );
}

function ReleaseAgain({
  onReleaseAgain,
  busy: pending,
}: {
  onReleaseAgain: () => void | Promise<unknown>;
  busy: boolean;
}) {
  const [waiting, setWaiting] = useState(false);
  const releaseAgain = async () => {
    if (waiting || pending) return;
    setWaiting(true);
    try {
      await onReleaseAgain();
    } catch {
      // Reported by the page; the button only has to be offered again.
    } finally {
      setWaiting(false);
    }
  };
  return (
    <div className="mb-3 rounded-xl border border-amber-500/30 bg-amber-500/5 px-3.5 py-3 text-[13px]">
      <p className="font-semibold text-[color:var(--tp-ink)]">This release was undone before any traffic moved</p>
      <p className="mt-1 text-[color:var(--tp-ink-2)]">
        Nothing reached production, so the same approved version can go again. The release
        guards are checked again first, as for any release.
      </p>
      <Button
        variant="primary"
        size="sm"
        className="mt-2.5"
        busy={waiting}
        disabled={pending}
        onClick={() => void releaseAgain()}
      >
        <RotateCcw className="h-3.5 w-3.5" />
        Release again
      </Button>
    </div>
  );
}
