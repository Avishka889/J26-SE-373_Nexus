import { scrollMotion } from "@/shared/utils/motion";
import { useEffect, useMemo, useRef, useState } from "react";
import { Check, HelpCircle, Lightbulb, ListChecks, MessageSquare, Pencil, Search, X } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { StageSection, TraceChips } from "@/shared/ui/stage";
import { Button } from "@/shared/ui/primitives";
import { Chip, Metric, Note, Panel } from "@/shared/ui/phase";
import { scrollToSection } from "@/shared/hooks/useScrollSpy";
import type {
  Assumption,
  DesignSnapshot,
  ParsedRequirement,
  RequirementPriority,
  RequirementType,
} from "../../api/types";
import type { useDesignMutations } from "../../hooks/useDesign";
import {
  applyRequirementFilter,
  EMPTY_FILTER,
  toggleIn,
  type RequirementFilter,
} from "../../model/requirementFilter";
import { CompactRow, ShowingCount } from "../lists/CompactRow";

type Mutations = ReturnType<typeof useDesignMutations>;

const typeTone = { functional: "info", quality: "caution", constraint: "neutral" } as const;
const typeLabel = { functional: "Functional", quality: "Quality", constraint: "Constraint" } as const;
const priorityLabel = { must: "Must", should: "Should", could: "Could" } as const;

const ALL_TYPES: RequirementType[] = ["functional", "quality", "constraint"];
const ALL_PRIORITIES: RequirementPriority[] = ["must", "should", "could"];

export function StageRequirements({
  snapshot,
  mutations,
  focusedRequirementId,
  onClearFocus,
  onJump,
  onOpenChat,
  onContinueWithAnswers,
  onContinueWithAssumptions,
}: {
  snapshot: DesignSnapshot;
  mutations: Mutations;
  focusedRequirementId: string | null;
  onClearFocus: () => void;
  onJump: (requirementId: string) => void;
  /** Opens and focuses the conversation panel, where questions are answered. */
  onOpenChat: () => void;
  /** Going on from the questions the run paused on, with the answers or the assumptions. */
  onContinueWithAnswers?: () => void | Promise<unknown>;
  onContinueWithAssumptions?: () => void | Promise<unknown>;
}) {
  const lowConfidence = snapshot.requirements.filter((r) => r.lowConfidence);
  const openQuestions = snapshot.questions.filter((q) => !q.answer);
  const liveAssumptions = snapshot.assumptions.filter((a) => !a.dismissed);
  const source = `Requirements Analysis, design version ${snapshot.requirementsVersion}`;

  const questions = (
    <StageSection id="requirements-questions">
      <QuestionsPointer
        open={openQuestions.length}
        answered={snapshot.questions.length - openQuestions.length}
        onOpenChat={onOpenChat}
        paused={snapshot.questionsPending}
        notesWaiting={snapshot.queuedChanges.length}
        onContinueWithAnswers={onContinueWithAnswers}
        onContinueWithAssumptions={onContinueWithAssumptions}
      />
    </StageSection>
  );

  return (
    <div className="space-y-5">
      {/* While the design waits on them, the questions are what this stage is
          for, so they come first rather than below everything it read. */}
      {snapshot.questionsPending && questions}
      <StageSection id="requirements-summary">
        <Panel
          icon={<ListChecks className="h-4 w-4" />}
          label="What was read from your input"
          title="Counts, not a score. Confidence belongs to each requirement, not to the phase."
        >
          {/* Each tile is a way into the block it counts, so the number and the
              thing it describes are one click apart rather than a scroll. */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <TileLink sectionId="requirements-list" label={`${snapshot.requirements.length} requirements`}>
              <Metric source={source} label="Requirements found" value={snapshot.requirements.length} size="sm" />
            </TileLink>
            <TileLink sectionId="requirements-list" label="the ones worth a closer look">
              <Metric
                source={source}
                label="Needs a closer look"
                value={lowConfidence.length}
                tone={lowConfidence.length > 0 ? "caution" : "pass"}
                note={lowConfidence.length > 0 ? "low confidence" : "all read clearly"}
                size="sm"
              />
            </TileLink>
            <TileLink sectionId="requirements-assumptions" label="the assumptions">
              <Metric source={source} label="Assumptions" value={liveAssumptions.length} size="sm" />
            </TileLink>
            <TileLink sectionId="requirements-questions" label="the open questions">
              <Metric
                source={source}
                label="Open questions"
                value={openQuestions.length}
                tone={openQuestions.length > 0 ? "caution" : "pass"}
                note={openQuestions.length > 0 ? "answer before approving" : "none outstanding"}
                size="sm"
              />
            </TileLink>
          </div>
        </Panel>
      </StageSection>

      <StageSection id="requirements-list">
        <RequirementList
          requirements={snapshot.requirements}
          mutations={mutations}
          focusedRequirementId={focusedRequirementId}
          onClearFocus={onClearFocus}
        />
      </StageSection>

      <StageSection id="requirements-assumptions">
        <AssumptionsBlock
          assumptions={liveAssumptions}
          dismissed={snapshot.assumptions.filter((a) => a.dismissed)}
          mutations={mutations}
          onJump={onJump}
          onOpenChat={onOpenChat}
        />
      </StageSection>

      {!snapshot.questionsPending && questions}
    </div>
  );
}

/** A summary tile that scrolls to what it counts. */
function TileLink({
  sectionId,
  label,
  children,
}: {
  sectionId: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={`Go to ${label}`}
      onClick={() => scrollToSection(sectionId)}
      className="rounded-xl text-left transition-colors hover:bg-[color:var(--tp-surface-2)]"
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------- requirement list */

function RequirementList({
  requirements,
  mutations,
  focusedRequirementId,
  onClearFocus,
}: {
  requirements: ParsedRequirement[];
  mutations: Mutations;
  focusedRequirementId: string | null;
  onClearFocus: () => void;
}) {
  const [filter, setFilter] = useState<RequirementFilter>(EMPTY_FILTER);
  const [openIds, setOpenIds] = useState<string[]>([]);
  const [expandAll, setExpandAll] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const focusRef = useRef<HTMLLIElement | null>(null);

  const visible = useMemo(
    () => applyRequirementFilter(requirements, filter),
    [requirements, filter],
  );

  // A trace chip elsewhere asked for this row: bring it into view, and let the
  // ring fade rather than leaving the page highlighted for good.
  useEffect(() => {
    if (!focusedRequirementId) return;
    focusRef.current?.scrollIntoView({ block: "center", behavior: scrollMotion() });
    const timer = window.setTimeout(onClearFocus, 2400);
    return () => window.clearTimeout(timer);
  }, [focusedRequirementId, onClearFocus]);

  // The jumped-to row is open because it is the jumped-to row, derived rather
  // than pushed into state by the effect above: the reader who followed a trace
  // chip wants the whole record, not one truncated line.
  const isOpen = (id: string) => expandAll || openIds.includes(id) || id === focusedRequirementId;
  const toggle = (id: string) => {
    setExpandAll(false);
    setOpenIds((ids) => toggleIn(ids, id));
  };

  return (
    <Panel
      label="Requirements"
      title="Each one carries its own confidence, and every artifact traces back to these ids."
      action={
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            setExpandAll((v) => !v);
            setOpenIds([]);
          }}
        >
          {expandAll ? "Collapse all" : "Expand all"}
        </Button>
      }
      bodyClassName="p-0"
    >
      <div className="border-b border-[color:var(--tp-line)] px-4 py-3">
        <FilterBar filter={filter} onChange={setFilter} />
        <div className="mt-2">
          <ShowingCount
            showing={visible.length}
            total={requirements.length}
            noun="requirements"
            onClear={() => setFilter(EMPTY_FILTER)}
          />
        </div>
      </div>

      {visible.length === 0 ? (
        <div className="px-4 py-6">
          <Note>
            No requirement matches these filters. Nothing has been hidden permanently: clear them to
            see all {requirements.length} again.
          </Note>
        </div>
      ) : (
        <ul>
          {visible.map((requirement) => {
            const open = isOpen(requirement.id);
            const editing = requirement.id === editingId;
            const focused = requirement.id === focusedRequirementId;

            return (
              <CompactRow
                key={requirement.id}
                rowId={requirement.id}
                open={open}
                focused={focused}
                onToggle={() => toggle(requirement.id)}
                lead={
                  <span className="flex min-w-0 items-baseline gap-2">
                    {/* The id appears here and nowhere else in the row: a chip
                        below pointing at the row's own id was a link to itself. */}
                    <span className="tp-mono shrink-0 text-[11px] font-semibold text-[color:var(--tp-ink-2)]">
                      {requirement.id}
                    </span>
                    <span
                      className={cn(
                        "min-w-0 text-[13px] text-[color:var(--tp-ink)]",
                        !open && "truncate",
                      )}
                    >
                      {requirement.text}
                    </span>
                  </span>
                }
                tags={
                  <>
                    <Chip tone={typeTone[requirement.type]}>{typeLabel[requirement.type]}</Chip>
                    <Chip>{priorityLabel[requirement.priority]}</Chip>
                    {requirement.qualityAttribute && <Chip>{requirement.qualityAttribute}</Chip>}
                    {requirement.adjusted && <Chip tone="info">Adjusted</Chip>}
                    {requirement.lowConfidence && <Chip tone="caution">Check</Chip>}
                  </>
                }
                trailing={
                  <span
                    className="tp-num text-sm"
                    style={{ color: requirement.lowConfidence ? "var(--tp-caution)" : undefined }}
                    title="How confidently this was read from your input"
                  >
                    {requirement.confidence}%
                  </span>
                }
              >
                {editing ? (
                  <div>
                    <textarea
                      autoFocus
                      rows={2}
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      className="w-full resize-none rounded-xl border border-[color:var(--tp-line)] bg-transparent px-3 py-2 text-[13px] outline-none focus:border-blue-500/50"
                    />
                    <Note className="mt-1.5">
                      Marks this requirement as adjusted. It does not regenerate the design: say what
                      changed in the chat for that.
                    </Note>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="primary"
                        disabled={!draft.trim()}
                        onClick={async () => {
                          try {
                            await mutations.editRequirement.mutateAsync({
                              id: requirement.id,
                              text: draft.trim(),
                            });
                            setEditingId(null);
                          } catch {
                            // Reported where it failed; the correction stays open.
                          }
                        }}
                      >
                        <Check className="h-3.5 w-3.5" />
                        Save
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => setEditingId(null)}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {/* The tags live behind the fold on a narrow screen, so the
                        opened row is where they are always readable. */}
                    <div className="flex flex-wrap items-center gap-1.5 md:hidden">
                      <Chip tone={typeTone[requirement.type]}>{typeLabel[requirement.type]}</Chip>
                      <Chip>{priorityLabel[requirement.priority]}</Chip>
                      {requirement.qualityAttribute && <Chip>{requirement.qualityAttribute}</Chip>}
                      {requirement.adjusted && <Chip tone="info">Adjusted</Chip>}
                      {requirement.lowConfidence && <Chip tone="caution">Check</Chip>}
                    </div>

                    {requirement.sourceQuote ? (
                      <p className="tp-den italic leading-relaxed">
                        from your input: {requirement.sourceQuote}
                      </p>
                    ) : (
                      <Note>
                        Inferred rather than read: no sentence in your input says this directly,
                        which is why its confidence is low.
                      </Note>
                    )}

                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={`Edit ${requirement.id}`}
                      onClick={() => {
                        setEditingId(requirement.id);
                        setDraft(requirement.text);
                      }}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                      Correct the wording
                    </Button>
                  </div>
                )}
              </CompactRow>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

/* ---------------------------------------------------------------- filters */

function FilterBar({
  filter,
  onChange,
}: {
  filter: RequirementFilter;
  onChange: (next: RequirementFilter) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <label className="relative min-w-[9rem] flex-1">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[color:var(--tp-muted)]" />
        <span className="sr-only">Search the requirements</span>
        <input
          value={filter.search}
          onChange={(e) => onChange({ ...filter, search: e.target.value })}
          placeholder="Search"
          className="w-full rounded-lg border border-[color:var(--tp-line)] bg-transparent py-1.5 pl-8 pr-2.5 text-[12px] outline-none focus:border-blue-500/50"
        />
      </label>

      <div className="flex flex-wrap items-center gap-1.5">
        {ALL_TYPES.map((type) => (
          <FilterChip
            key={type}
            on={filter.types.includes(type)}
            onClick={() => onChange({ ...filter, types: toggleIn(filter.types, type) })}
          >
            {typeLabel[type]}
          </FilterChip>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {ALL_PRIORITIES.map((priority) => (
          <FilterChip
            key={priority}
            on={filter.priorities.includes(priority)}
            onClick={() =>
              onChange({ ...filter, priorities: toggleIn(filter.priorities, priority) })
            }
          >
            {priorityLabel[priority]}
          </FilterChip>
        ))}
      </div>

      <FilterChip
        on={filter.needsAttention}
        tone="caution"
        onClick={() => onChange({ ...filter, needsAttention: !filter.needsAttention })}
      >
        Needs attention
      </FilterChip>
    </div>
  );
}

function FilterChip({
  on,
  tone,
  onClick,
  children,
}: {
  on: boolean;
  tone?: "caution";
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        "rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors",
        on
          ? tone === "caution"
            ? "border-amber-500/50 bg-amber-500/[0.1] text-amber-700 dark:text-amber-300"
            : "border-blue-500/50 bg-blue-500/[0.08] text-blue-600 dark:text-blue-300"
          : "border-[color:var(--tp-line)] text-[color:var(--tp-ink-2)] hover:border-blue-500/40 hover:text-blue-600",
      )}
    >
      {children}
    </button>
  );
}

/* --------------------------------------------------------- assumptions */

function AssumptionsBlock({
  assumptions,
  dismissed,
  mutations,
  onJump,
  onOpenChat,
}: {
  assumptions: Assumption[];
  /** Dismissed ones stay listed, with a way back: a dismissal could not be undone. */
  dismissed: Assumption[];
  mutations: Mutations;
  onJump: (id: string) => void;
  onOpenChat: () => void;
}) {
  const [openIds, setOpenIds] = useState<string[]>([]);

  const restore =
    dismissed.length > 0 ? (
      <div className="border-t border-[color:var(--tp-line)] px-4 py-3">
        <p className="tp-label">Dismissed</p>
        <ul className="mt-2 space-y-1.5">
          {dismissed.map((assumption) => (
            <li key={assumption.id} className="flex flex-wrap items-center gap-2 text-[13px]">
              <span className="tp-mono text-[11px] font-semibold text-[color:var(--tp-ink-2)]">
                {assumption.id}
              </span>
              <span className="min-w-0 flex-1 text-[color:var(--tp-ink-2)] line-through decoration-[color:var(--tp-muted)]">
                {assumption.text}
              </span>
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  mutations.dismissAssumption
                    .mutateAsync({ id: assumption.id, dismissed: false })
                    .catch(() => undefined)
                }
              >
                Restore
              </Button>
            </li>
          ))}
        </ul>
      </div>
    ) : null;

  if (assumptions.length === 0) {
    return (
      <Panel icon={<Lightbulb className="h-4 w-4" />} label="Assumptions" bodyClassName="p-0">
        <div className="px-4 py-3">
          <Note>
            {dismissed.length > 0
              ? "Every assumption was dismissed."
              : "Nothing was assumed: every requirement came from something you wrote."}
          </Note>
        </div>
        {restore}
      </Panel>
    );
  }

  return (
    <Panel
      icon={<Lightbulb className="h-4 w-4" />}
      label="Assumptions"
      title="What the analysis proceeded on where your input did not say. Dismiss any that do not apply, or correct one in the chat."
      meta={`${assumptions.length} standing`}
      bodyClassName="p-0"
    >
      <ul>
        {assumptions.map((assumption) => (
          <CompactRow
            key={assumption.id}
            rowId={assumption.id}
            open={openIds.includes(assumption.id)}
            onToggle={() => setOpenIds((ids) => toggleIn(ids, assumption.id))}
            lead={
              <span className="flex min-w-0 items-baseline gap-2">
                <span className="tp-mono shrink-0 text-[11px] font-semibold text-[color:var(--tp-ink-2)]">
                  {assumption.id}
                </span>
                <span
                  className={cn(
                    "min-w-0 text-[13px] text-[color:var(--tp-ink)]",
                    !openIds.includes(assumption.id) && "truncate",
                  )}
                >
                  {assumption.text}
                </span>
              </span>
            }
            tags={assumption.edited ? <Chip tone="info">Edited</Chip> : undefined}
          >
            <div className="space-y-2">
              <TraceChips traces={assumption.traces} onJump={onJump} />
              <div className="flex flex-wrap gap-2">
                {/* Two controls, no text field. Correcting an assumption is a
                    sentence, and sentences belong in the one composer this
                    phase has. */}
                <Button size="sm" variant="outline" onClick={onOpenChat}>
                  <MessageSquare className="h-3.5 w-3.5" />
                  Correct this in chat
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  title="Dismiss: this assumption does not apply"
                  onClick={() =>
                    mutations.dismissAssumption
                      .mutateAsync({ id: assumption.id, dismissed: true })
                      .catch(() => undefined)
                  }
                >
                  <X className="h-3.5 w-3.5" />
                  Does not apply
                </Button>
              </div>
            </div>
          </CompactRow>
        ))}
      </ul>
      {restore}
    </Panel>
  );
}

/* ------------------------------------------------------------- questions */

/**
 * A pointer, not a form.
 *
 * A question is the agent speaking and waiting for a reply, so it is asked and
 * answered in the conversation panel. Duplicating it here as a second input
 * would give the phase two places to say the same thing and two places to keep in
 * step.
 */
function QuestionsPointer({
  open,
  answered,
  onOpenChat,
  paused = false,
  notesWaiting = 0,
  onContinueWithAnswers,
  onContinueWithAssumptions,
}: {
  open: number;
  answered: number;
  onOpenChat: () => void;
  /** The run waits on these questions before it builds the rest of the design. */
  paused?: boolean;
  /** Notes written while it waits, which go into the analysis with the answers. */
  notesWaiting?: number;
  /** May resolve when the server has answered, which keeps the button busy. */
  onContinueWithAnswers?: () => void | Promise<unknown>;
  onContinueWithAssumptions?: () => void | Promise<unknown>;
}) {
  if (paused) {
    const canAnswer = answered > 0 || notesWaiting > 0;
    return (
      <Panel
        icon={<HelpCircle className="h-4 w-4" />}
        label="Questions for you"
        meta={open > 0 ? `${open} open` : `${answered} answered`}
      >
        <p className="text-[13px] font-medium text-[color:var(--tp-ink)]">
          The rest of the design waits on{" "}
          {open + answered === 1 ? "this question" : "these questions"}.
        </p>
        <Note className="mt-1">
          {open > 0
            ? "Answer them in the conversation, then continue with your answers: the requirements are analysed again with them. Or continue with the assumptions the analysis made, and answer later at the review."
            : "Every question is answered. Continue with your answers, and the requirements are analysed again with them."}
        </Note>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {open > 0 && (
            <Button size="sm" variant={canAnswer ? "outline" : "primary"} onClick={onOpenChat}>
              <MessageSquare className="h-3.5 w-3.5" />
              Answer in chat
            </Button>
          )}
          <Button
            size="sm"
            variant={canAnswer ? "primary" : "outline"}
            disabled={!canAnswer}
            onClick={onContinueWithAnswers}
          >
            Continue with my answers
          </Button>
          <Button size="sm" variant="outline" onClick={onContinueWithAssumptions}>
            Continue with the assumptions
          </Button>
        </div>
        {!canAnswer && (
          <p className="tp-den mt-1.5 text-[12px]">
            Answer a question first to continue with your answers.
          </p>
        )}
      </Panel>
    );
  }

  if (open === 0) {
    return (
      <Panel icon={<HelpCircle className="h-4 w-4" />} label="Questions for you">
        <Note>
          {answered > 0
            ? `Every question is answered (${answered}). Answers reach the design only when applied: Apply the answers in Design Review regenerates it with them.`
            : "Nothing was unclear enough to ask about."}
        </Note>
      </Panel>
    );
  }

  return (
    <Panel
      icon={<HelpCircle className="h-4 w-4" />}
      label="Questions for you"
      meta={`${open} open`}
    >
      <p className="text-[13px] text-[color:var(--tp-ink)]">
        {open === 1 ? "One question is" : `${open} questions are`} waiting on you, in the
        conversation.
      </p>
      <Note className="mt-1">
        They are asked in the chat because a question is the agent waiting for a reply, and an
        answer there is recorded against the requirements it concerns.
      </Note>
      <Button size="sm" variant="primary" className="mt-3" onClick={onOpenChat}>
        <MessageSquare className="h-3.5 w-3.5" />
        Answer in chat
      </Button>
    </Panel>
  );
}
