import { useState } from "react";
import { ChevronDown, ListOrdered, RefreshCw, Target } from "lucide-react";
import { Button } from "@/shared/ui/primitives";
import { cn } from "@/shared/utils/cn";
import { StageSection, TraceChips } from "@/shared/ui/stage";
import { Chip, Hairline, Metric, Note, Panel } from "@/shared/ui/phase";
import type { ConsistencyFinding, SprintPlan, UserStory } from "../../api/types";

const priorityLabel = { must: "Must", should: "Should", could: "Could" } as const;
const priorityTone = { must: "fail", should: "caution", could: "neutral" } as const;

/**
 * A design phase plans work. It does not report on work, so there is no burndown
 * and no completed points here: nothing has been built yet, and showing progress
 * against unwritten code would be fiction.
 */
export function StageSprintPlan({
  sprint,
  version,
  behind,
  onPlanAgain,
  onJump,
}: {
  sprint: SprintPlan | null;
  /** The design version the plan belongs to, which its tiles name. */
  version: number;
  /** The stories ranked on a priority a person has since corrected. */
  behind: ConsistencyFinding[];
  /** Plan the sprint again, which calls the model once. */
  onPlanAgain: () => void;
  onJump: (requirementId: string) => void;
}) {
  // The sprint plan is a leaf stage, so the phase can reach the gate without one.
  // An absent plan says so rather than taking the page down.
  if (!sprint) {
    return (
      <Panel
        label="No plan was written"
        title="The sprint plan did not finish, so there are no stories to show yet."
      >
        <Note>
          Nothing was planned for this version. Retry the Sprint Planning stage, and the stories and
          their estimates appear here.
        </Note>
      </Panel>
    );
  }

  const overCapacity = sprint.estimatedPoints > sprint.velocityAssumption.points;
  const source = `Sprint Planning, design version ${version}`;

  return (
    <div className="space-y-5">
      {behind.length > 0 && (
        // A corrected priority changed the requirement and nothing planned from
        // it, and the plan said nothing (review item C1-2).
        <Panel
          label="Behind the requirements"
          title="This plan was ranked before a priority was corrected"
          className="border-amber-500/30"
        >
          <ul className="space-y-1">
            {behind.map((finding) => (
              <li key={finding.reason} className="tp-den">
                {finding.reason}
              </li>
            ))}
          </ul>
          <Note className="mt-2">
            Planning again writes the stories again with one model call, ranks them on the priorities
            held now, and keeps the ids of the stories that carry over.
          </Note>
          <Button size="sm" variant="outline" className="mt-2" onClick={onPlanAgain}>
            <RefreshCw className="h-3.5 w-3.5" />
            Plan the sprint again
          </Button>
        </Panel>
      )}

      <StageSection id="sprint-summary">
        <Panel
          icon={<Target className="h-4 w-4" />}
          label={sprint.sprintName}
          title={sprint.goal}
          meta="Proposed, not committed. Nothing here has been started."
        >
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Metric
              source={source}
              label="Points"
              value={sprint.estimatedPoints}
              note="estimated"
              tone={overCapacity ? "caution" : undefined}
              size="sm"
            />
            <Metric
              source={`an assumption, not a measurement: ${source}`}
              label="Assumed velocity"
              value={sprint.velocityAssumption.points}
              note="points per sprint"
              size="sm"
            />
            <Metric source={source} label="Stories proposed" value={sprint.proposed.length} size="sm" />
            <Metric source={source} label="Left in the backlog" value={sprint.backlog.length} size="sm" />
          </div>

          <Hairline className="my-4" />

          <Note>
            Velocity is {sprint.velocityAssumption.basis}. Points are estimates, and both numbers should
            be revisited once a real sprint has been delivered.
            {overCapacity && " As proposed, this sprint is above the assumed velocity."}
          </Note>
        </Panel>
      </StageSection>

      <StageSection id="sprint-proposed">
        <StoryList
          title={sprint.sprintName}
          subtitle="Ordered by priority. These are the stories the first sprint would take on."
          stories={sprint.proposed}
          needs={sprint.backlogDependencies}
          onJump={onJump}
        />
      </StageSection>

      <StageSection id="sprint-backlog">
        <StoryList
          title="Backlog"
          subtitle="Everything else, in the order it would be picked up."
          stories={sprint.backlog}
          onJump={onJump}
        />
      </StageSection>
    </div>
  );
}

function StoryList({
  title,
  subtitle,
  stories,
  needs = [],
  onJump,
}: {
  title: string;
  subtitle: string;
  stories: UserStory[];
  /** The stories here that need one left in the backlog, and why. */
  needs?: SprintPlan["backlogDependencies"];
  onJump: (requirementId: string) => void;
}) {
  return (
    <Panel
      icon={<ListOrdered className="h-4 w-4" />}
      label={title}
      title={subtitle}
      meta={`${stories.reduce((sum, s) => sum + s.points, 0)} points estimated`}
      bodyClassName="p-0"
    >
      <ul>
        {stories.map((story, i) => (
          <StoryRow
            key={story.id}
            story={story}
            first={i === 0}
            needs={needs.filter((one) => one.storyId === story.id)}
            onJump={onJump}
          />
        ))}
      </ul>
    </Panel>
  );
}

function StoryRow({
  story,
  first,
  needs,
  onJump,
}: {
  story: UserStory;
  first: boolean;
  needs: SprintPlan["backlogDependencies"];
  onJump: (requirementId: string) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <li className={cn(!first && "border-t border-[color:var(--tp-line)]")}>
      {/* The trace chips are links in their own right, so they sit beside the
          expand control rather than inside it: a button cannot contain a button. */}
      <div className="px-5 py-3.5">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex w-full items-start justify-between gap-3 text-left"
        >
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-2">
              <span className="tp-mono text-[11px] font-semibold text-[color:var(--tp-ink-2)]">
                {story.id}
              </span>
              <Chip tone={priorityTone[story.priority]}>{priorityLabel[story.priority]}</Chip>
              <Chip>{story.epic}</Chip>
              {needs.map((one) => (
                <Chip key={one.needs} tone="caution">{`Needs ${one.needs}`}</Chip>
              ))}
            </span>
            <span className="mt-1.5 block text-[13px] text-[color:var(--tp-ink)]">{story.title}</span>
            {/* Outside the fold, because it is a reason to change the sprint and
                a reader approving the plan should not have to open a row to
                find it (review item C1-5). */}
            {needs.map((one) => (
              <span key={one.needs} className="tp-den mt-1 block">
                Needs {one.needs}, which is in the backlog: {one.because}. Move it into the build
                when you scope the sprint, or approve knowing this story cannot be finished without
                it.
              </span>
            ))}
          </span>
          <span className="flex shrink-0 items-center gap-3">
            <span className="text-right">
              <span className="tp-num block text-base">{story.points}</span>
              <span className="tp-den">estimated</span>
            </span>
            <ChevronDown
              className={cn(
                "h-4 w-4 text-[color:var(--tp-muted)] transition-transform",
                open && "rotate-180",
              )}
            />
          </span>
        </button>
        <div className="mt-1.5">
          <TraceChips traces={story.traces} onJump={onJump} />
        </div>
      </div>

      {open && (
        <div className="border-t border-[color:var(--tp-line)] bg-[color:var(--tp-surface-2)] px-5 py-3.5">
          <p className="tp-label">Acceptance criteria</p>
          <ul className="mt-2 space-y-2.5">
            {story.acceptance.map((criterion) => (
              <li key={criterion.id} className="text-[12.5px] leading-relaxed">
                <span className="tp-mono text-[10px] uppercase tracking-wide text-[color:var(--tp-muted)]">
                  Given
                </span>{" "}
                <span className="text-[color:var(--tp-ink-2)]">{criterion.given}</span>
                <br />
                <span className="tp-mono text-[10px] uppercase tracking-wide text-[color:var(--tp-muted)]">
                  When
                </span>{" "}
                <span className="text-[color:var(--tp-ink-2)]">{criterion.when}</span>
                <br />
                <span className="tp-mono text-[10px] uppercase tracking-wide text-[color:var(--tp-muted)]">
                  Then
                </span>{" "}
                <span className="text-[color:var(--tp-ink)]">{criterion.then}</span>
              </li>
            ))}
          </ul>
          <Note className="mt-3">
            Testing generates its first tests from these, so they are part of the contract rather than
            a description of it.
          </Note>
        </div>
      )}
    </li>
  );
}
