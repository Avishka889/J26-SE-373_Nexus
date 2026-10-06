import { useState } from "react";
import { useDraft } from "@/shared/hooks";
import { Activity, ListTree, Send } from "lucide-react";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { Button, Table, Td, Th } from "@/shared/ui/primitives";
import { Chip, Note, Panel } from "@/shared/ui/phase";
import { StageSection } from "@/shared/ui/stage";
import type { DeploymentView, FeedbackDecisionInput } from "../../api/types";
import type { DeploymentPageView, FeedbackView } from "../../model/view";
import { shortHash } from "../../model/view";
import { EmptyNote, Facts, Mono, StateChip } from "../bits";
import { formatWhen } from "@/shared/utils/time";

/** A ledger state as the end of a sentence about a release: "which ...". */
const LEDGER_STATE: Record<DeploymentView["state"], string> = {
  pending: "is pending",
  running: "is running",
  succeeded: "succeeded",
  compensated: "was undone before it moved any traffic",
  failed: "failed",
  "awaiting-rollback-approval": "waits on a rollback decision",
  "rolled-back": "was rolled back",
  "kept-unverified": "was kept after a declined rollback, unverified",
};

type FeedbackItemView = FeedbackView["items"][number];

function FeedbackRow({
  item,
  busy,
  onDecide,
  onAskSend,
  draftKey,
}: {
  item: FeedbackItemView;
  busy: boolean;
  onDecide: (decision: FeedbackDecisionInput["decision"], note: string) => Promise<boolean>;
  /** Sending regenerates the design, so it is asked about before it happens. */
  onAskSend: () => void;
  /** Where the note's draft is kept, so it survives the stage being closed. */
  draftKey: string;
}) {
  const [note, setNote] = useDraft(draftKey);
  const decide = async (decision: FeedbackDecisionInput["decision"]) => {
    if (await onDecide(decision, note)) setNote("");
  };
  // Held until the reason is written: it was enabled only to be refused.
  const noReason = note.trim() === "";
  const noteId = `feedback-note-${item.id}`;
  return (
    <li className="min-w-0 py-3" data-feedback-item={item.id}>
      <p className="flex flex-wrap items-center gap-2">
        <span className="break-words text-[13px] font-semibold">{item.summary}</span>
        <Chip>{item.kind}</Chip>
      </p>
      <Note className="mt-1 break-words text-[12.5px]">{item.evidence}</Note>
      <p className="mt-2 rounded-xl border border-[color:var(--tp-line)] px-3 py-2 text-[13px]">
        <span className="tp-label block">Suggested requirement</span>
        <span className="break-words">{item.suggestedRequirement}</span>
      </p>
      {item.evidenceRef && <p className="tp-den mt-1 break-all">Evidence: {item.evidenceRef}</p>}
      {item.decision ? (
        <p className="mt-2 text-[13px]">
          {item.decision.decision === "sent"
            ? `Sent to requirements by ${item.decision.by} at ${formatWhen(item.decision.at)}, as design version ${item.decision.designVersion}.`
            : `Dismissed by ${item.decision.by} at ${formatWhen(item.decision.at)}: ${item.decision.note ?? ""}`}
        </p>
      ) : (
        <div className="mt-2 space-y-2">
          <label className="block" htmlFor={noteId}>
            <span className="tp-label">Note, required to dismiss</span>
            <textarea
              id={noteId}
              rows={2}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Why this should not reach requirements"
              className="mt-1 w-full resize-none rounded-xl border border-[color:var(--tp-line-strong)] bg-transparent px-3 py-2 text-[13px] outline-none focus:border-blue-500/50"
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" size="sm" busy={busy} onClick={onAskSend}>
              <Send className="h-3.5 w-3.5" />
              Send to requirements
            </Button>
            <Button
              variant="outline"
              size="sm"
              busy={busy}
              disabled={noReason}
              title={noReason ? "Write why it should not reach requirements first" : undefined}
              onClick={() => void decide("dismissed")}
            >
              Dismiss
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

/**
 * Monitoring: the release that serves now, watched for a bounded window.
 *
 * Bounded, because a free host probed forever never sleeps. Every number names
 * where it came from and over which window, and a window that watched a
 * release since replaced is shown as that, not as the health of what serves.
 * The monitor never starts a rollback: finding a release down raises the
 * decision on the Release stage and says so in the conversation.
 */
export function StageMonitoring({
  view,
  busy,
  watching,
  onWatch,
  onDecideFeedback,
  onSendFeedback,
  isDark,
}: {
  view: DeploymentPageView;
  busy: boolean;
  /** A monitoring window is running now, as the server says (`watching`). */
  watching: boolean;
  onWatch: () => void;
  onDecideFeedback: (
    itemId: string,
    decision: FeedbackDecisionInput["decision"],
    note: string,
  ) => Promise<boolean>;
  /** Sends suggestions as one design change. */
  onSendFeedback: (itemIds: string[]) => Promise<boolean>;
  isDark: boolean;
}) {
  const { report, watched, watchesServing, canWatch, cannotWatch } = view.monitoring;
  const serving = view.release.serving;
  // What is about to be sent, while the reader is asked. Sending was one
  // click, and it opens a design version and runs a paid regeneration.
  const [sending, setSending] = useState<string[] | null>(null);
  const undecided = view.feedback.items.filter((item) => !item.decision).map((item) => item.id);

  return (
    <div className="space-y-4">
      <StageSection id="monitoring-health">
        <Panel
          icon={<Activity className="h-4 w-4 text-blue-400" />}
          label="Health"
          title={
            report
              ? `The last window watched deploy version ${watched?.deployVersion ?? report.version}, which ${watched ? LEDGER_STATE[watched.state] : "is not on the ledger"}.`
              : "No window has been watched yet."
          }
          meta={report ? `Source: ${report.source}; window ${formatWhen(report.windowStart)} to ${formatWhen(report.windowEnd)}` : undefined}
          action={
            <Button variant="outline" size="sm" busy={busy || watching} disabled={!canWatch} onClick={onWatch} title={cannotWatch || undefined}>
              {watching ? "Watching" : "Watch the serving release"}
            </Button>
          }
        >
          {!canWatch && <Note className="mb-3 text-[12.5px]">{cannotWatch}</Note>}
          {report && !watchesServing && serving && (
            <Note className="mb-3 text-[12.5px]">
              What serves now is deploy version {serving.deployVersion}, which this window did not
              watch, so its state below is not the state of what serves.
            </Note>
          )}
          {report ? (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <span className="tp-label">State at the end of the window</span>
                <StateChip state={report.currentState} />
                <Chip tone={report.fingerprintMatches ? "pass" : "neutral"}>
                  {report.fingerprintMatches === null
                    ? "fingerprint not read"
                    : report.fingerprintMatches
                      ? `served ${shortHash(report.expectedCandidateHash)}`
                      : "served another candidate"}
                </Chip>
              </div>
              <Facts
                rows={[
                  ["Watched", <Mono key="u">{report.urls.join(", ")}</Mono>],
                  [
                    "Probes",
                    <span key="p" title={`Classified by ${report.ruleId}`}>
                      every {report.probeIntervalSeconds} s
                    </span>,
                  ],
                  [
                    "Degraded above",
                    `${report.thresholds.degradedP95Ms} ms at the 95th percentile`,
                  ],
                  [
                    "Idle before the window",
                    report.idleSeconds === null
                      ? "not on record"
                      : `${Math.round(report.idleSeconds)} s, since ${report.idleFrom === "released" ? "the release" : "the last probe"}`,
                  ],
                ]}
              />
              <Table className="mt-3">
                <thead>
                  <tr>
                    <Th>Probe</Th>
                    <Th>Answered</Th>
                    <Th>p50</Th>
                    <Th>p95</Th>
                  </tr>
                </thead>
                <tbody>
                  {report.probes.map((probe) => (
                    <tr key={probe.probe}>
                      <Td>
                        <Mono>{probe.probe}</Mono>
                        {/* Its time is shown and does not decide the state after
                            the window's first request: two slow answers from it
                            called a healthy release degraded. */}
                        {probe.probe.endsWith("/release.json") && (
                          <span className="tp-den block text-[11.5px]">
                            The release&apos;s fingerprint. Its time counts only as the window&apos;s
                            first request.
                          </span>
                        )}
                      </Td>
                      <Td>
                        {probe.ok} of {probe.samples}
                      </Td>
                      <Td>{probe.p50Ms === null ? "none" : `${Math.round(probe.p50Ms)} ms`}</Td>
                      <Td>{probe.p95Ms === null ? "none" : `${Math.round(probe.p95Ms)} ms`}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <ol className="mt-3 space-y-1.5">
                {report.states.map((interval) => (
                  <li key={interval.start} className="flex flex-wrap items-center gap-2 text-[12.5px]">
                    <StateChip state={interval.state} />
                    <span className="tp-den">
                      {formatWhen(interval.start)} to {formatWhen(interval.end)}, {interval.samples} rounds:
                    </span>
                    <span className="min-w-0 break-words">{interval.evidence}</span>
                  </li>
                ))}
              </ol>
            </>
          ) : (
            <EmptyNote>
              A window probes the serving release for a bounded time and reports what it saw. None
              has run on this project yet.
            </EmptyNote>
          )}
        </Panel>
      </StageSection>

      <StageSection id="monitoring-events">
        <Panel
          icon={<ListTree className="h-4 w-4 text-blue-400" />}
          label="Events"
          title="What happened to the watched release, in order."
        >
          {report && report.events.length > 0 ? (
            <ol className="space-y-1.5">
              {report.events.map((event) => (
                <li key={`${event.at}-${event.kind}`} className="flex flex-wrap items-center gap-2 text-[12.5px]">
                  <span className="tp-den">{formatWhen(event.at)}</span>
                  <Chip>{event.kind}</Chip>
                  <span className="min-w-0 break-words">{event.detail}</span>
                </li>
              ))}
            </ol>
          ) : (
            <EmptyNote>No event in the last window.</EmptyNote>
          )}
        </Panel>
      </StageSection>

      <StageSection id="monitoring-feedback">
        <Panel
          icon={<Send className="h-4 w-4 text-blue-400" />}
          label="Feedback for requirements"
          title="What production suggests the next requirements should say. Nothing reaches them until you send it."
          meta={
            view.feedback.deployVersion
              ? `From the window over deploy version ${view.feedback.deployVersion}`
              : undefined
          }
          action={
            undecided.length > 1 ? (
              <Button variant="outline" size="sm" busy={busy} onClick={() => setSending(undecided)}>
                <Send className="h-3.5 w-3.5" />
                Send all {undecided.length} as one change
              </Button>
            ) : undefined
          }
        >
          {view.feedback.items.length === 0 ? (
            <EmptyNote>Nothing to suggest from the last window.</EmptyNote>
          ) : (
            <ul className="divide-y divide-[color:var(--tp-line)]">
              {view.feedback.items.map((item) => (
                <FeedbackRow
                  key={item.id}
                  item={item}
                  busy={busy}
                  onDecide={(decision, note) => onDecideFeedback(item.id, decision, note)}
                  onAskSend={() => setSending([item.id])}
                  draftKey={`${view.projectId}:feedback:${item.id}`}
                />
              ))}
            </ul>
          )}
        </Panel>
      </StageSection>

      {sending && (
        <ConfirmDialog
          title={
            sending.length === 1
              ? "Send this suggestion to requirements?"
              : `Send these ${sending.length} suggestions to requirements?`
          }
          body={
            `${sending.length === 1 ? "It becomes" : "They become"} one change note on the design. ` +
            "That opens a new design version and runs Requirements and Design again on every " +
            "stage, which calls the model. Code Generation, Testing and Deployment then have a " +
            "new design to build from, and each is reviewed again."
          }
          confirmLabel="Send to requirements"
          isDark={isDark}
          onCancel={() => setSending(null)}
          onConfirm={() => {
            const ids = sending;
            setSending(null);
            void onSendFeedback(ids);
          }}
        />
      )}
    </div>
  );
}
