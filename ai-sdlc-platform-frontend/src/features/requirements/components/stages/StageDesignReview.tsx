import {
  ArrowRight,
  CheckCircle2,
  HelpCircle,
  History,
  MessageSquare,
  MessageSquareWarning,
  Unlink,
} from "lucide-react";
import type { DesignStageId } from "@/types/project";
import { Button } from "@/shared/ui/primitives";
import { ActorMark, Chip, Hairline, Metric, Note, Panel } from "@/shared/ui/phase";
import type { DesignSnapshot } from "../../api/types";
import type { DomainModel } from "../../model/domain";
import { STAGE_META } from "../../model/stages";
import { regeneratingStageIds } from "../../model/outdated";
import { StageSection, TraceChips } from "@/shared/ui/stage";
import { Spinner } from "@/shared/ui/Spinner";
import { formatWhen } from "@/shared/utils/time";

/**
 * The phase gate. Everything generated above, gathered in one place, plus the
 * one decision that starts Code Generation. Item level decisions happened inside
 * their stages; this is the only phase level one.
 */
export function StageDesignReview({
  snapshot,
  domain,
  onGoToStage,
  onJump,
  onContinue,
  onOpenChat,
  onApplyAnswers,
  applying = false,
}: {
  snapshot: DesignSnapshot;
  domain: DomainModel;
  onGoToStage: (stageId: DesignStageId) => void;
  onJump: (requirementId: string) => void;
  onContinue: () => void;
  /** Opens and focuses the conversation, where questions are answered. */
  onOpenChat: () => void;
  /** Regenerates the design with the answers given; resolves once the server has it. */
  onApplyAnswers: () => void | Promise<unknown>;
  applying?: boolean;
}) {
  const decision = snapshot.gate.decision;
  const version = snapshot.requirementsVersion;
  const openQuestions = snapshot.questions.filter((q) => !q.answer);
  const answered = snapshot.questions.filter((q) => q.answer);
  const liveAssumptions = snapshot.assumptions.filter((a) => !a.dismissed);
  const lowConfidence = snapshot.requirements.filter((r) => r.lowConfidence);
  // Both of these can be absent, and this page is where that bites. The gate
  // opens once the run reaches it, and the recommendation and the plan are leaf
  // stages that are allowed to fail without stopping the run: so the review can
  // be readable while one of the things it summarises was never produced. Reading
  // through them took the whole page down behind the error boundary.
  const architecture = snapshot.architecture;
  const sprint = snapshot.sprint;
  const selected = architecture?.candidates.find(
    (c) => c.id === architecture.selectedCandidateId,
  );
  const regenerating = regeneratingStageIds(snapshot);
  const uncovered = snapshot.wireframes.coverage.filter((row) => !row.covered);
  // Errors first: a defect and a note read very differently, and the reader
  // scanning this list is deciding whether to approve.
  const consistencyErrors = snapshot.consistency.filter((f) => f.severity === "error");
  const orderedFindings = [
    ...consistencyErrors,
    ...snapshot.consistency.filter((f) => f.severity !== "error"),
  ];

  return (
    <div className="space-y-5">
      <StageSection id="review-checks" className="space-y-5">
        {decision?.kind === "approved" && (
          <Panel className="border-emerald-500/30 bg-emerald-500/[0.04]">
            <div className="flex flex-wrap items-start gap-3">
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" />
              <div className="min-w-0 flex-1">
                <p className="text-[15px] font-semibold text-[color:var(--tp-ink)]">
                  Design approved for requirements version {decision.version}
                </p>
                <p className="tp-den mt-1 flex flex-wrap items-center gap-1.5">
                  <ActorMark actor={decision.by} kind="human" /> at {formatWhen(decision.at)}
                </p>
                <Note className="mt-2">
                  If the requirements change after this, the approval covers the version it was given
                  for and this phase asks again.
                </Note>
                <Button variant="primary" className="mt-3" onClick={onContinue}>
                  Continue to Code Generation
                  <ArrowRight className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          </Panel>
        )}

        {decision?.kind === "changes" && (
          <Panel className="border-amber-500/30 bg-amber-500/[0.04]">
            <div className="flex flex-wrap items-start gap-3">
              <MessageSquareWarning className="mt-0.5 h-5 w-5 shrink-0 text-amber-500" />
              <div className="min-w-0 flex-1">
                <p className="text-[15px] font-semibold text-[color:var(--tp-ink)]">Changes requested</p>
                <p className="tp-prose mt-1">{decision.note}</p>
                <p className="tp-den mt-1.5 flex flex-wrap items-center gap-1.5">
                  <ActorMark actor={decision.by} kind="human" /> at {formatWhen(decision.at)}
                </p>
                {regenerating.length > 0 && (
                  <p className="tp-den mt-2 flex items-center gap-2">
                    <Spinner size="xs" decorative />
                    Regenerating {regenerating.map((id) => STAGE_META[id].label).join(", ")}
                  </p>
                )}
              </div>
            </div>
          </Panel>
        )}

        {openQuestions.length > 0 && (
          <Panel
            icon={<HelpCircle className="h-4 w-4" />}
            label="Open questions from the analysis"
            title="Unanswered, so a decision is not made around them. Answering records; applying the answers regenerates the design."
            className="border-amber-500/30"
            action={
              /* Straight into the conversation, because that is where a question
                 is asked and where answering it clears it everywhere. Sending
                 the reader to the requirements stage would land them beside a
                 pointer telling them to come here. */
              <Button size="sm" variant="primary" onClick={onOpenChat}>
                <MessageSquare className="h-3.5 w-3.5" />
                Answer in chat
              </Button>
            }
          >
            <ul className="space-y-2">
              {openQuestions.map((question) => (
                <li key={question.id} className="rounded-xl border border-[color:var(--tp-line)] px-3.5 py-2.5">
                  <p className="text-[13px] leading-relaxed text-[color:var(--tp-ink)]">
                    {question.question}
                  </p>
                  <div className="mt-1.5">
                    <TraceChips traces={question.traces} onJump={onJump} />
                  </div>
                </li>
              ))}
            </ul>
          </Panel>
        )}

        {answered.length > 0 && (
          <Panel
            icon={<HelpCircle className="h-4 w-4" />}
            label={`${answered.length} ${answered.length === 1 ? "answer" : "answers"} not applied yet`}
            title="Applying them regenerates the design from Requirements Analysis with your answers, which runs the model again. Until then the design is as it was."
            action={
              <Button
                size="sm"
                variant="primary"
                busy={applying}
                onClick={() => void Promise.resolve(onApplyAnswers()).catch(() => undefined)}
              >
                Apply the answers
              </Button>
            }
          >
            <ul className="space-y-2">
              {answered.map((question) => (
                <li key={question.id} className="rounded-xl border border-[color:var(--tp-line)] px-3.5 py-2.5">
                  <p className="text-[13px] leading-relaxed text-[color:var(--tp-ink)]">{question.question}</p>
                  <p className="tp-den mt-1">{question.answer}</p>
                </li>
              ))}
            </ul>
          </Panel>
        )}

        {snapshot.consistency.length > 0 && (
          /* The checks that compare artifacts against each other. They belong
             here and nowhere else: none of them can be seen from inside the
             stage they concern, and this is the moment somebody decides. They
             do not block the decision, because approving is the reader's call
             and a check that refused would be the tool overruling them. */
          <Panel
            icon={<Unlink className="h-4 w-4" />}
            label="These artifacts disagree"
            title="Checks that compare the artifacts against each other, surfaced here so a decision is not made around them."
            className={consistencyErrors.length > 0 ? "border-red-500/30" : "border-amber-500/30"}
          >
            <ul className="space-y-2">
              {orderedFindings.map((finding, index) => (
                <li
                  key={`${finding.ruleId}-${index}`}
                  className="rounded-xl border border-[color:var(--tp-line)] px-3.5 py-2.5"
                >
                  <div className="flex flex-wrap items-start gap-2">
                    <Chip tone={finding.severity === "error" ? "fail" : "caution"}>
                      {finding.severity === "error" ? "Fix before approving" : "Worth checking"}
                    </Chip>
                    <p className="min-w-0 flex-1 text-[13px] leading-relaxed text-[color:var(--tp-ink)]">
                      {finding.reason}
                    </p>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <TraceChips traces={finding.traces} onJump={onJump} />
                    {finding.stageId !== null && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => onGoToStage(finding.stageId as DesignStageId)}
                      >
                        Open {STAGE_META[finding.stageId].label}
                      </Button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </Panel>
        )}
      </StageSection>


      <StageSection id="review-artifacts" className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <SummaryCard
          label="Requirements"
          stageId="requirements"
          onGoToStage={onGoToStage}
          meta={`version ${snapshot.requirementsVersion}`}
        >
          <div className="grid grid-cols-3 gap-3">
            <Metric source={`Requirements Analysis, design version ${version}`} label="Requirements" value={snapshot.requirements.length} size="sm" />
            <Metric source={`Requirements Analysis, design version ${version}`} label="Assumptions" value={liveAssumptions.length} size="sm" />
            <Metric
              source={`Requirements Analysis, design version ${version}`}
              label="Open questions"
              value={openQuestions.length}
              tone={openQuestions.length > 0 ? "caution" : "pass"}
              size="sm"
            />
          </div>
          {lowConfidence.length > 0 && (
            <Note className="mt-3">
              {lowConfidence.length} were read with low confidence and are worth checking:{" "}
              {lowConfidence.map((r) => r.id).join(", ")}.
            </Note>
          )}
        </SummaryCard>

        <SummaryCard
          label="Architecture"
          stageId="architecture-recommendation"
          onGoToStage={onGoToStage}
          meta={selected ? "selected" : "nothing selected"}
        >
          {selected ? (
            <>
              <p className="flex flex-wrap items-center gap-2">
                <span className="text-[15px] font-semibold text-[color:var(--tp-ink)]">
                  {selected.name}
                </span>
                <Chip tone="pass">Selected</Chip>
                {selected.id === architecture?.recommendedCandidateId && (
                  <Chip tone="info">Was recommended</Chip>
                )}
              </p>
              <Note className="mt-2">{selected.rationale}</Note>
              <p className="tp-den mt-2">
                Chosen by {architecture?.selectedBy} at {formatWhen(architecture?.selectedAt)}
              </p>
            </>
          ) : architecture ? (
            <Note>
              No shape has been selected yet. The recommendation is{" "}
              {
                architecture.candidates.find(
                  (c) => c.id === architecture.recommendedCandidateId,
                )?.name
              }
              , but the choice is yours to record.
            </Note>
          ) : (
            <Note>
              No shapes were scored for this version, so there is nothing to choose between.
              Retry the Architecture Recommendation stage.
            </Note>
          )}
        </SummaryCard>

        <SummaryCard
          label="Design artifacts"
          stageId="uml-diagrams"
          onGoToStage={onGoToStage}
          meta={`${snapshot.uml.diagrams.length} diagrams`}
        >
          <div className="grid grid-cols-3 gap-3">
            <Metric source={`Domain Model, design version ${version}`} label="Entities" value={domain.entities.length} size="sm" />
            <Metric source={`Domain Model, design version ${version}`} label="Actors" value={domain.primaryActors.length + domain.externalSystems.length} size="sm" />
            <Metric source={`UML Diagrams, design version ${version}`} label="Diagrams" value={snapshot.uml.diagrams.length} size="sm" />
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => onGoToStage("uml-diagrams")}>
              Open UML Diagrams
            </Button>
            <Button size="sm" variant="outline" onClick={() => onGoToStage("wireframes")}>
              Open Wireframes
            </Button>
          </div>
        </SummaryCard>

        <SummaryCard
          label="Plan"
          stageId="sprint-plan"
          onGoToStage={onGoToStage}
          meta={sprint ? sprint.sprintName : "not planned"}
        >
          {sprint ? (
            <>
              <div className="grid grid-cols-3 gap-3">
                <Metric
                  source={`Sprint Planning, design version ${version}`}
                  label="Points"
                  value={sprint.estimatedPoints}
                  note="estimated"
                  size="sm"
                />
                <Metric source={`Sprint Planning, design version ${version}`} label="Stories" value={sprint.proposed.length} size="sm" />
                <Metric
                  source={`Wireframes against Sprint Planning, design version ${version}`}
                  label="Screens missing"
                  value={uncovered.length}
                  tone={uncovered.length > 0 ? "caution" : "pass"}
                  size="sm"
                />
              </div>
              <Note className="mt-3">{sprint.goal}</Note>
            </>
          ) : (
            <Note>
              No plan was written for this version, so there is nothing to estimate against.
              Retry the Sprint Planning stage.
            </Note>
          )}
        </SummaryCard>
      </StageSection>

      <StageSection id="review-decision">
        {snapshot.gate.history.length > 0 && (
          <Panel icon={<History className="h-4 w-4" />} label="Earlier decisions">
            <ul className="space-y-2">
              {snapshot.gate.history.map((entry, i) => (
                <li key={`${entry.at}-${i}`} className="tp-den flex flex-wrap items-center gap-2">
                  <Chip tone={entry.kind === "approved" ? "pass" : "caution"}>
                    {entry.kind === "approved" ? "Approved" : "Changes requested"}
                  </Chip>
                  version {entry.version}, by {entry.by} at {formatWhen(entry.at)}
                  {entry.note && <span>: {entry.note}</span>}
                </li>
              ))}
            </ul>
            <Hairline className="my-3" />
            <Note>
              A decision covers the requirements version it was given for. When the requirements move
              on, it goes here and the phase asks again.
            </Note>
          </Panel>
        )}
      </StageSection>
    </div>
  );
}

function SummaryCard({
  label,
  meta,
  stageId,
  onGoToStage,
  children,
}: {
  label: string;
  meta: string;
  stageId: DesignStageId;
  onGoToStage: (stageId: DesignStageId) => void;
  children: React.ReactNode;
}) {
  return (
    <Panel
      label={label}
      meta={meta}
      action={
        <Button size="sm" variant="ghost" onClick={() => onGoToStage(stageId)}>
          Open
          <ArrowRight className="h-3.5 w-3.5" />
        </Button>
      }
    >
      {children}
    </Panel>
  );
}
