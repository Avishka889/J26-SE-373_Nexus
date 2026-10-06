import { useId, useState } from "react";
import { useDraft } from "@/shared/hooks";
import { ClipboardCheck, History, ListChecks, ShieldAlert } from "lucide-react";
import { Button, Table, Td, Th } from "@/shared/ui/primitives";
import { Chip, Note, Panel } from "@/shared/ui/phase";
import { Select } from "@/shared/ui/Select";
import { StageSection } from "@/shared/ui/stage";
import { DEPLOY_STAGE_IDS, type DeployStageId } from "@/types/project";
import type {
  DeploySnapshot,
  ReleaseTarget,
  ReleaseTargetOption,
  UpdateDecisionInput,
} from "../../api/types";
import {
  keptInTheDatabase,
  stageLabel,
  type DeploymentPageView,
  type UpdateView,
} from "../../model/view";
import { EmptyNote, LevelChip } from "../bits";
import { formatWhen } from "@/shared/utils/time";

/** Each release guard in a reader's words; the codes are the record's, shown as a tooltip. */
const GUARD_NAMES: Record<string, string> = {
  G1: "Update decisions",
  G2: "Rollback plan",
  G3: "Staging",
  G4: "Test approval",
  G5: "Cloud release",
  G6: "Release target",
  G7: "Pipeline validation",
  G8: "Security findings",
};

type Decision = UpdateDecisionInput["decision"];

const DECISION_WORDS: Record<Decision, string> = {
  approved: "Approved",
  rejected: "Left out",
  deferred: "Deferred",
};

const STEP_TONE = {
  done: "pass",
  attention: "fail",
  waiting: "caution",
  running: "info",
  pending: "neutral",
} as const;

/**
 * One update's decision, where the reviewer makes it.
 *
 * A High update's approval and any update left out carry a note: the server
 * refuses them without one, and saying so beside the button saves a refusal.
 */
function UpdateDecision({
  update,
  busy,
  closed,
  onDecide,
  draftKey,
}: {
  update: UpdateView;
  busy: boolean;
  /** No review waits, so there is nothing a decision here would count towards. */
  closed: boolean;
  onDecide: (decision: Decision, note: string) => Promise<boolean>;
  /** Where the note's draft is kept, so it survives the stage being closed. */
  draftKey: string;
}) {
  const [note, setNote] = useDraft(draftKey);
  const noNote = note.trim() === "";
  const [changing, setChanging] = useState(false);
  const decided = update.decision?.decision ?? null;
  // A Low update ships under its strategy with no decision owed, so its form
  // stays closed unless the reviewer wants it out or held back.
  const [opened, setOpened] = useState(update.level !== "low");
  const noteId = `decision-note-${update.updateId}`;

  return (
    <li className="min-w-0 py-3" data-update-decision={update.package}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="break-words text-[13px] font-semibold text-[color:var(--tp-ink)]">
          {update.package}
        </span>
        <LevelChip level={update.level} />
        {update.decision?.needsDecision && !decided && <Chip tone="caution">needs your decision</Chip>}
        {update.leftOut && !decided && <Chip>not in this release</Chip>}
        {update.level === "low" && !decided && !update.leftOut && <Chip>ships automatically</Chip>}
      </div>

      {update.leftOut && !decided ? (
        // The candidate does not carry it, so no decision here counts towards
        // this release, and the release guard asks for none.
        <p className="tp-den mt-1 break-words">Left out of this candidate: {update.leftOut}.</p>
      ) : !decided && !opened ? (
        <Button variant="ghost" size="sm" className="mt-1" disabled={closed} onClick={() => setOpened(true)}>
          Leave out or defer
        </Button>
      ) : decided && !changing ? (
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
          <p className="text-[13px]">
            {DECISION_WORDS[decided]} by {update.decision?.by} at {formatWhen(update.decision?.at)}
            {update.decision?.note ? `: "${update.decision.note}"` : ""}
          </p>
          <Button variant="ghost" size="sm" disabled={closed} onClick={() => setChanging(true)}>
            Change
          </Button>
        </div>
      ) : (
        <div className="mt-2 space-y-2">
          <label className="block" htmlFor={noteId}>
            <span className="tp-label">
              {update.level === "high"
                ? "Review note, required to approve a High update"
                : "Note, required to leave it out"}
            </span>
            <textarea
              id={noteId}
              rows={2}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              className="mt-1 w-full resize-none rounded-xl border border-[color:var(--tp-line-strong)] bg-transparent px-3 py-2 text-[13px] outline-none focus:border-blue-500/50"
              placeholder={
                update.level === "high"
                  ? "What you checked before letting this ship"
                  : "Why, if you leave it out or defer it"
              }
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="primary"
              size="sm"
              busy={busy}
              // A High update is approved with what was checked, and the
              // server refuses it without: the button was enabled only to be
              // refused.
              disabled={closed || (update.level === "high" && noNote)}
              title={
                !closed && update.level === "high" && noNote
                  ? "Write what you checked before letting this ship first"
                  : undefined
              }
              onClick={async () => {
                if (await onDecide("approved", note)) {
                  setNote("");
                  setChanging(false);
                }
              }}
            >
              Approve
            </Button>
            <Button
              variant="outline"
              size="sm"
              busy={busy}
              disabled={closed || noNote}
              title={!closed && noNote ? "Write why you leave it out first" : undefined}
              onClick={async () => {
                if (await onDecide("rejected", note)) setNote("");
              }}
            >
              Leave out
            </Button>
            <Button
              variant="ghost"
              size="sm"
              busy={busy}
              disabled={closed}
              onClick={async () => {
                if (await onDecide("deferred", note)) setNote("");
              }}
            >
              Defer
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

/**
 * Deployment Review: the whole phase in one place, the decisions it needs,
 * and the audit of every decision taken.
 *
 * What stops the release is the server's list, shown as it computes it (the
 * release guards, G1 to G5). The page never decides by itself whether a
 * release may go ahead.
 */
export function StageReview({
  snapshot,
  view,
  targets,
  busy,
  goAhead,
  onGoAhead,
  onDecideUpdate,
  onChooseTarget,
  shownTarget,
  onChoosePolicy,
  onOpenStage,
  onOpenTesting,
}: {
  snapshot: DeploySnapshot;
  view: DeploymentPageView;
  targets: ReleaseTargetOption[];
  busy: boolean;
  /** The go ahead a cloud release needs, which the approval carries. */
  goAhead: boolean;
  onGoAhead: (given: boolean) => void;
  onDecideUpdate: (updateId: string, decision: Decision, note: string) => Promise<boolean>;
  onChooseTarget: (target: ReleaseTarget) => void;
  /** The target the dropdown shows: the one just chosen while it is saved, else the server's. */
  shownTarget?: ReleaseTarget;
  onChoosePolicy: (autoDeployLow: boolean) => void;
  onOpenStage: (stageId: DeployStageId) => void;
  /** Testing & Security, where a finding is fixed, dismissed or its risk accepted (G8). */
  onOpenTesting: () => void;
}) {
  const targetId = useId();
  const history = [
    ...(snapshot.gate.decision ? [snapshot.gate.decision] : []),
    ...[...snapshot.gate.history].reverse(),
  ];
  const decided = snapshot.decisions.filter((one) => one.decision);
  const packageOf = (updateId: string) =>
    view.updates.find((one) => one.updateId === updateId)?.package ?? updateId;

  return (
    <div className="space-y-4">
      <StageSection id="review-summary">
        <Panel
          icon={<ClipboardCheck className="h-4 w-4 text-blue-400" />}
          label="Summary"
          title={`Deploy version ${view.version}: every stage, and where the release would go.`}
        >
          {snapshot.deployedCodeVersion > 0 && (
            // Which code goes out, and under which tests: the review did not say (C4-7).
            <p className="mb-2 text-[13px]">
              {`Deploy version ${view.version} ships code version ${snapshot.deployedCodeVersion}` +
                (snapshot.analysedTestVersion > 0
                  ? `, with the tests approved at test version ${snapshot.analysedTestVersion}.`
                  : ".")}
            </p>
          )}
          <ul className="divide-y divide-[color:var(--tp-line)]">
            {DEPLOY_STAGE_IDS.map((id) => (
              <li key={id}>
                <button
                  type="button"
                  onClick={() => onOpenStage(id)}
                  className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 py-2 text-left hover:text-blue-600"
                >
                  <span className="min-w-0 flex-1 basis-40 text-[13px] font-medium">{stageLabel(id)}</span>
                  <Chip tone={STEP_TONE[view.steps[id].state]}>{view.steps[id].hint}</Chip>
                </button>
              </li>
            ))}
          </ul>
          <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-3">
            <div className="flex min-w-0 flex-wrap items-center gap-2 text-[13px]">
              <label htmlFor={targetId} className="tp-label">
                Release to
              </label>
              <Select<ReleaseTarget>
                id={targetId}
                size="sm"
                value={shownTarget ?? snapshot.releaseTarget}
                disabled={busy || view.running}
                onChange={onChooseTarget}
                options={targets.map((one) => ({
                  value: one.id,
                  label: one.label,
                  note: one.usable ? undefined : `Unavailable: ${one.reason}`,
                  disabled: !one.usable,
                }))}
              />
            </div>
            {snapshot.plan && (
              // G6 refuses a release to a target the analysis did not plan for;
              // it said so only after the change was made.
              <span className="tp-den basis-full text-[12px]">
                This version was planned for{" "}
                {snapshot.plan.target === "cloud" ? "the cloud" : "this machine"}. Another target
                needs a new analysis: request changes, and the next version is planned for it.
              </span>
            )}
            <label className="flex min-w-0 items-center gap-2 text-[13px]">
              <input
                type="checkbox"
                checked={snapshot.autoDeployLow}
                disabled={busy}
                onChange={(event) => onChoosePolicy(event.target.checked)}
              />
              Ship Low updates without a review, once a verified release exists
            </label>
          </div>
          {snapshot.releaseTarget === "cloud" && (
            <label className="mt-3 flex min-w-0 items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[13px]">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={goAhead}
                disabled={busy}
                onChange={(event) => onGoAhead(event.target.checked)}
              />
              <span className="min-w-0">
                Go ahead: this release runs on Vercel and Render through GitHub Actions and spends
                their minutes. The approval carries this, and the server refuses a cloud release
                without it.
              </span>
            </label>
          )}
          {snapshot.releaseTarget === "cloud" && (
            <div data-cloud-resources>
              <Note className="mt-2 text-[12.5px]">
                {snapshot.cloud ? (
                  <>
                    The frontend goes to the Vercel project {snapshot.cloud.vercel.name} at{" "}
                    <a
                      className="underline"
                      href={snapshot.cloud.vercel.origin}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {snapshot.cloud.vercel.origin}
                    </a>
                    , and the backend to the Render service {snapshot.cloud.render.name} at{" "}
                    <a
                      className="underline"
                      href={snapshot.cloud.render.origin}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {snapshot.cloud.render.origin}
                    </a>
                    , both this project&apos;s own.{" "}
                    {snapshot.cloud.database ? (
                      !snapshot.candidate ? (
                        <span data-database>
                          Its database is {snapshot.cloud.database.database} on the Atlas cluster{" "}
                          {snapshot.cloud.database.cluster}.
                        </span>
                      ) : keptInTheDatabase(snapshot.candidate) ? (
                        <span data-database>
                          Its records are kept in the database {snapshot.cloud.database.database}{" "}
                          on the Atlas cluster {snapshot.cloud.database.cluster}, which a restart
                          or a release leaves as it is.
                        </span>
                      ) : (
                        <span data-database>
                          The platform made its database {snapshot.cloud.database.database} on the
                          Atlas cluster {snapshot.cloud.database.cluster}, but this code keeps its
                          records in memory, so a restart or a release empties them; code
                          generated again reads the database.
                        </span>
                      )
                    ) : (
                      <span data-database>
                        It keeps its records in memory, so a restart or a release empties them:
                        add MongoDB Atlas in Settings to keep them.
                      </span>
                    )}
                  </>
                ) : (
                  "The analysis with the cloud target makes this project's own Vercel project, a free Render web service and, when Settings has a MongoDB Atlas connection, its own database, from the tokens in Settings, before it generates the deployment files."
                )}
              </Note>
            </div>
          )}
          {targets.find((one) => one.id === "cloud" && !one.usable) && (
            <Note className="mt-2 text-[12.5px]">
              Cloud releases: {targets.find((one) => one.id === "cloud")?.reason}.
            </Note>
          )}
        </Panel>
      </StageSection>

      <StageSection id="review-decisions">
        <Panel
          icon={<ListChecks className="h-4 w-4 text-blue-400" />}
          label="Decisions"
          title="Medium and High updates need a person; a High approval carries a review note."
          meta={`${view.needDecision} still owed`}
        >
          {view.blocking.length > 0 && (
            <div className="mb-3 rounded-xl border border-red-500/30 bg-red-500/5 px-3.5 py-3">
              <p className="flex items-center gap-2 text-[13px] font-semibold">
                <ShieldAlert className="h-4 w-4 text-red-500" />
                What stops this release now
              </p>
              <ul className="mt-1.5 space-y-1">
                {view.blocking.map((blocker, index) => (
                  <li key={`${blocker.code}-${index}`} className="flex flex-wrap items-start gap-2 text-[12.5px]">
                    {/* The guard in words; its code stays a tooltip, for whoever reads the record. */}
                    <span title={`Release guard ${blocker.code}`}>
                      <Chip tone="fail">{GUARD_NAMES[blocker.code] ?? "Release check"}</Chip>
                    </span>
                    <span className="min-w-0 flex-1 break-words">{blocker.message}</span>
                    {/* G3 is about the candidate, which Staging Verification
                        builds and can build again while this review waits. */}
                    {blocker.code === "G3" && (
                      <button
                        type="button"
                        onClick={() => onOpenStage("staging-verification")}
                        className="shrink-0 text-[12.5px] font-medium text-blue-700 hover:underline dark:text-blue-300"
                      >
                        Go to Staging Verification
                      </button>
                    )}
                    {/* G8 is about a finding, which Testing & Security decides. */}
                    {blocker.code === "G8" && (
                      <button
                        type="button"
                        onClick={onOpenTesting}
                        className="shrink-0 text-[12.5px] font-medium text-blue-700 hover:underline dark:text-blue-300"
                      >
                        Go to Testing & Security
                      </button>
                    )}
                    {/* G7 is about the generated pipeline, whose validation the
                        CI/CD Pipeline stage shows file by file. */}
                    {blocker.code === "G7" && (
                      <button
                        type="button"
                        onClick={() => onOpenStage("pipeline-generation")}
                        className="shrink-0 text-[12.5px] font-medium text-blue-700 hover:underline dark:text-blue-300"
                      >
                        Go to CI/CD Pipeline
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {view.updates.length === 0 ? (
            <EmptyNote>There is nothing to decide at this deploy version.</EmptyNote>
          ) : (
            <ul className="divide-y divide-[color:var(--tp-line)]">
              {view.updates.map((update) => (
                <UpdateDecision
                  key={update.updateId}
                  update={update}
                  busy={busy}
                  closed={!view.decisionPending}
                  onDecide={(decision, note) => onDecideUpdate(update.updateId, decision, note)}
                  draftKey={`${view.projectId}:update:${update.updateId}`}
                />
              ))}
            </ul>
          )}
        </Panel>
      </StageSection>

      <StageSection id="review-audit">
        <Panel
          icon={<History className="h-4 w-4 text-blue-400" />}
          label="Audit"
          title="Every decision on this phase, newest first, with who took it."
        >
          {history.length === 0 && decided.length === 0 ? (
            <EmptyNote>No decision has been taken on this phase yet.</EmptyNote>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Decision</Th>
                  <Th>By</Th>
                  <Th>At</Th>
                  <Th>Note</Th>
                </tr>
              </thead>
              <tbody>
                {history.map((decision) => (
                  <tr key={`gate-${decision.version}-${decision.at}-${decision.kind}`}>
                    <Td>
                      {decision.kind === "approved" ? "Approved" : "Changes requested"} deploy version{" "}
                      {decision.version}
                    </Td>
                    <Td>{decision.by}</Td>
                    <Td>{formatWhen(decision.at)}</Td>
                    <Td className="break-words">{decision.note ?? ""}</Td>
                  </tr>
                ))}
                {decided.map((one) => (
                  <tr key={`update-${one.updateId}`}>
                    <Td>
                      {DECISION_WORDS[one.decision as Decision]} {packageOf(one.updateId)} at{" "}
                      {one.levelAtDecision}
                    </Td>
                    <Td>{one.by}</Td>
                    <Td>{formatWhen(one.at)}</Td>
                    <Td className="break-words">{one.note ?? ""}</Td>
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
