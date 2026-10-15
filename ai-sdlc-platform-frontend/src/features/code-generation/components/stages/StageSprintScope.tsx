import { Check, Minus } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { Chip, Metric, Note, Panel } from "@/shared/ui/phase";
import { Button } from "@/shared/ui/primitives";
import { StageSection, TraceChips } from "@/shared/ui/stage";
import type { CodeSnapshot, NextSprint } from "../../api/types";

const priorityLabel = { must: "Must", should: "Should", could: "Could" } as const;
const priorityTone = { must: "fail", should: "caution", could: "neutral" } as const;

/**
 * What this build covers.
 *
 * The first stage, and the one that decides everything after it: the contract
 * is inferred from the screens the in scope stories are traced to, so moving a
 * story changes the endpoints and the code. Saying that out loud beside the
 * toggle is what stops a reader treating it as a filter.
 *
 * The build grows a sprint at a time: each story in it names the sprint it was
 * planned in, and the next sprint is shown before it is planned, divided as
 * the sprint plan divides one.
 */
export function StageSprintScope({
  snapshot,
  onToggle,
  onPlanNextSprint,
  onOpenScreens,
  onOpenRequirement,
  busy,
  planning = false,
  reviewOpen = false,
}: {
  snapshot: CodeSnapshot;
  onToggle: (storyId: string, inScope: boolean) => void;
  /** Put the next sprint's stories into the build and generate once. */
  onPlanNextSprint: () => void;
  onOpenScreens: (screenIds: string[]) => void;
  /** Opens the requirement on the design page: the chips did nothing. */
  onOpenRequirement: (requirementId: string) => void;
  busy: boolean;
  /** The next sprint is being planned: its button says so until the server answers. */
  planning?: boolean;
  /** This build's code review waits on a decision, which the next sprint waits for. */
  reviewOpen?: boolean;
}) {
  const scope = snapshot.scope;
  if (!scope) return null;

  const inScope = scope.stories.filter((story) => story.inScope);
  const source = `Sprint Scope, code version ${snapshot.codeVersion}`;
  const points = inScope.reduce((total, story) => total + story.points, 0);
  const screens = new Set(inScope.flatMap((story) => story.traces.screenIds));

  return (
    <div className="space-y-5">
      <StageSection id="scope-summary">
        <Panel label={scope.sprintName} title="Everything generated below is generated for these stories.">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Metric source={source} label="In scope" value={String(inScope.length)} />
            <Metric source={source} label="Out of scope" value={String(scope.stories.length - inScope.length)} />
            <Metric source={source} label="Points" value={String(points)} />
            <Metric source={source} label="Screens covered" value={String(screens.size)} />
          </div>
          <Note className="mt-3">
            Moving a story changes what the contract covers, so the API contract and both
            sides of the code regenerate at a new version. Nothing already generated is
            deleted: earlier versions stay, and the contract diff says what moved.
          </Note>
        </Panel>
      </StageSection>

      <StageSection id="scope-stories">
        <Panel label="Stories">
          <ul className="space-y-2">
            {scope.stories.map((story) => (
              <li
                key={story.id}
                className={cn(
                  "rounded-xl border px-3.5 py-3 transition-colors",
                  story.inScope
                    ? "border-[color:var(--tp-line-strong)]"
                    : "border-[color:var(--tp-line)] opacity-70",
                )}
              >
                <div className="flex flex-wrap items-start gap-3">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onToggle(story.id, !story.inScope)}
                    title={story.inScope ? "Take out of this build" : "Put into this build"}
                    // Named for its story: every toggle was "Take out of this build".
                    aria-label={`${story.inScope ? "Take" : "Put"} ${story.id}, ${story.title}, ${story.inScope ? "out of" : "into"} this build`}
                    aria-pressed={story.inScope}
                    className={cn(
                      "mt-0.5 flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center rounded border transition-colors disabled:cursor-default disabled:opacity-40",
                      story.inScope
                        ? "border-blue-500/60 bg-blue-500/15 text-blue-600 dark:text-blue-300"
                        : "border-[color:var(--tp-line-strong)] text-[color:var(--tp-muted)]",
                    )}
                  >
                    {story.inScope ? <Check className="h-3 w-3" /> : <Minus className="h-3 w-3" />}
                  </button>
                  <div className="min-w-0 flex-1">
                    <p className="text-[13px] font-medium text-[color:var(--tp-ink)]">
                      <span className="tp-mono mr-2 text-[11px] text-[color:var(--tp-muted)]">
                        {story.id}
                      </span>
                      {story.title}
                    </p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      {story.inScope && <Chip tone="info">Sprint {story.sprint}</Chip>}
                      <span className="tp-den">{story.points} points</span>
                      <TraceChips
                        traces={story.traces.requirementIds}
                        onJump={onOpenRequirement}
                        label="Traces to"
                      />
                      {story.traces.screenIds.length > 0 ? (
                        <button
                          type="button"
                          onClick={() => onOpenScreens(story.traces.screenIds)}
                          className="tp-den cursor-pointer underline decoration-dotted underline-offset-2 hover:text-blue-600"
                        >
                          {story.traces.screenIds.length} screens
                        </button>
                      ) : (
                        // Said rather than hidden: a story with no screen is
                        // one the contract cannot be inferred from, and that is
                        // exactly what a reader needs to know before approving.
                        <span className="tp-den">no screens cover this story</span>
                      )}
                      {story.decidedBy !== "system default" && (
                        <span className="tp-den">{story.decidedBy} decided this</span>
                      )}
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      </StageSection>

      <StageSection id="scope-next-sprint">
        <NextSprintPanel
          next={snapshot.nextSprint}
          onPlan={onPlanNextSprint}
          busy={busy}
          planning={planning}
          reviewOpen={reviewOpen}
        />
      </StageSection>
    </div>
  );
}

/**
 * What planning the next sprint would add, before anyone asks.
 *
 * The stories come from the server, divided as the sprint plan divides a
 * sprint, so the page shows what the action will do rather than working it
 * out again here.
 */
function NextSprintPanel({
  next,
  onPlan,
  busy,
  planning,
  reviewOpen,
}: {
  next: NextSprint | null;
  onPlan: () => void;
  busy: boolean;
  planning: boolean;
  reviewOpen: boolean;
}) {
  if (!next) {
    return (
      <Panel label="Next sprint">
        <Note>
          The current design version has no sprint plan, so there is no backlog to plan the next
          sprint from.
        </Note>
      </Panel>
    );
  }
  if (next.stories.length === 0) {
    return (
      <Panel label="Next sprint">
        <Note>Every story in the sprint plan is in this build. There is no backlog left to plan.</Note>
      </Panel>
    );
  }
  return (
    <Panel
      label={`Next sprint: sprint ${next.number}`}
      title="The next stories from the backlog, as the sprint plan divides a sprint."
    >
      <ul className="space-y-2">
        {next.stories.map((story) => (
          <li
            key={story.id}
            className="flex flex-wrap items-center gap-2 rounded-xl border border-[color:var(--tp-line)] px-3.5 py-2.5"
          >
            <span className="tp-mono text-[11px] text-[color:var(--tp-muted)]">{story.id}</span>
            <Chip tone={priorityTone[story.priority]}>{priorityLabel[story.priority]}</Chip>
            <span className="min-w-0 flex-1 text-[13px] text-[color:var(--tp-ink)]">{story.title}</span>
            <span className="tp-den">{story.points} points</span>
          </li>
        ))}
      </ul>
      <p className="tp-den mt-3">
        {next.points} of a {next.velocity} point velocity assumption ({next.velocityBasis}).
      </p>
      <Note className="mt-3">
        Taken in priority order up to the velocity assumption, stopping at the first story that
        does not fit. Planning puts these stories into this build and generates the code once, at
        a new version. The stories already in the build stay in it.
      </Note>
      {reviewOpen && (
        // Planning it while this build's review was open decided the review as
        // requested changes: the next sprint goes on top of a reviewed build.
        <Note className="mt-3">
          Decide the code review first. Sprint {next.number} is planned on top of this build once
          it is approved.
        </Note>
      )}
      <div className="mt-3">
        <Button
          variant="primary"
          size="sm"
          busy={planning}
          disabled={busy || reviewOpen}
          onClick={onPlan}
        >
          {planning ? "Planning" : `Plan sprint ${next.number}`}
        </Button>
      </div>
    </Panel>
  );
}
