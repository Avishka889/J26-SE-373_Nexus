import { scrollMotion } from "@/shared/utils/motion";
import { useEffect, useRef } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { ChevronStepper } from "@/shared/ui/ChevronStepper";
import type { StepperStep } from "@/shared/ui/chevronStatus";
import { scrollToSection, useScrollSpy } from "@/shared/hooks/useScrollSpy";
import {
  nextStageIn,
  previousStageIn,
  stageIndexIn,
  type StageChrome,
  type StageSectionMeta,
} from "./types";

/**
 * Where you are in the phase, and where you can go, without scrolling back up.
 *
 * The full chevron row was the only way to change stage, so reading any stage
 * meant losing sight of the pipeline. This sticks under the phase tabs and
 * condenses once it does, because the full row plus the tabs plus the decision
 * bar was already most of a 1440 viewport.
 *
 * The anchor pills beside it are the reader's position within the open stage,
 * and they are the same jump the summary tiles and the trace chips use.
 */
export function StageNav<Id extends string>({
  chrome,
  steps,
  activeStage,
  onSelectStage,
  shortcut,
  narrow,
}: {
  chrome: StageChrome<Id>;
  steps: (StepperStep & { badge?: React.ReactNode; badgeLabel?: string })[];
  activeStage: Id;
  onSelectStage: (id: Id) => void;
  /**
   * The jump to the phase's decision, when there is one to make.
   *
   * A parameter rather than a hardcoded stage, because it survives condensing
   * and this is the form the reader sees most: stepping to the gate one arrow
   * at a time is six clicks in either phase. Null when the phase is not ready
   * to be decided.
   */
  shortcut: { id: Id; label: string; title: string } | null;
  /**
   * True when the conversation panel is taking its share of the width.
   *
   * At 1440 with the panel open the content column is about 790px, which is not
   * enough for eight chevrons: the row overflows and the stage pushed off the
   * end is Design Review, the one holding the decision. The condensed form is
   * not a nicety at that width, it is the only honest option.
   */
  narrow: boolean;
}) {
  const sections = chrome.sections[activeStage];
  const activeSection = useScrollSpy(sections.map((s) => s.id));

  const previous = previousStageIn(chrome, activeStage);
  const next = nextStageIn(chrome, activeStage);
  const position = stageIndexIn(chrome, activeStage) + 1;

  return (
    <>
      <div
        data-stage-rail
        className="sticky z-[12] -mx-4 border-b border-[color:var(--tp-line)] bg-[color:var(--tp-surface)] px-4 py-2 sm:-mx-6 sm:px-6 md:-mx-8 md:px-8"
        style={{ top: 0 }}
      >
        {/* The rail condenses for width, not for scrolling.
            It swapped on `stuck` too, so scrolling with the conversation closed
            replaced a rail that fitted perfectly well with a one line summary.
            That swap changed the bar's height at the exact scroll position that
            triggered it, which is what flickered, and then what clipped when the
            height was pinned to stop the flicker.
            The bar still sticks: that is CSS, and it is what a reader wants. Only
            the swap is gone, and with it the JS that detected sticking at all. */}
        <div className="flex w-full items-center">
          {narrow ? (
            <>
              {/* `narrow` means the conversation column is taking its share of
                  the width, and below lg it never is: the panel there is a
                  sheet over the work, not a column beside it. So the condensed
                  form applies only at lg and up, and the phone keeps the full
                  row scrolling inside itself, which is what the narrow width
                  sweep verifies. */}
              <div className="hidden w-full lg:block">
                <CondensedStages
                  chrome={chrome}
                  activeStage={activeStage}
                  position={position}
                  total={steps.length}
                  previous={previous}
                  next={next}
                  onSelectStage={onSelectStage}
                  shortcut={shortcut}
                />
              </div>
              <div className="w-full lg:hidden">
                <FullStages
                  steps={steps}
                  activeStage={activeStage}
                  onSelectStage={onSelectStage}
                />
              </div>
            </>
          ) : (
            <FullStages
              steps={steps}
              activeStage={activeStage}
              onSelectStage={onSelectStage}
            />
          )}
        </div>

        {sections.length > 1 && (
          <SectionAnchors sections={sections} activeSection={activeSection} />
        )}
      </div>
    </>
  );
}

/* ------------------------------------------------------------ the two rows */

function FullStages<Id extends string>({
  steps,
  activeStage,
  onSelectStage,
}: {
  steps: (StepperStep & { badge?: React.ReactNode; badgeLabel?: string })[];
  activeStage: Id;
  onSelectStage: (id: Id) => void;
}) {
  // The row gets the whole width. Anything sharing it costs one chevron, and the
  // one pushed off the end is always the last: Design Review, which holds the
  // decision this phase exists for.
  return (
    <ScrolledIntoView activeStage={activeStage}>
      <ChevronStepper
        steps={steps}
        selectedId={activeStage}
        onStepClick={(id) => onSelectStage(id as Id)}
      />
    </ScrolledIntoView>
  );
}

/**
 * Keep the open stage's chevron on screen.
 *
 * At 1440 the row scrolls horizontally and Design Review was the one clipped off
 * the end, which is the worst possible choice: it is the stage holding the
 * decision this phase exists for.
 */
function ScrolledIntoView({
  activeStage,
  children,
}: {
  activeStage: string;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const selected = ref.current?.querySelector<HTMLElement>(
      '[aria-current="step"]',
    );
    // `nearest` so a chevron already in view does not get yanked to the middle.
    selected?.scrollIntoView({
      behavior: scrollMotion(),
      block: "nearest",
      inline: "nearest",
    });
  }, [activeStage]);

  // min-w-0 and flex-1, both load bearing: this is a flex item of the rail row,
  // and a flex item defaults to min-width:auto, so it refused to shrink below
  // the stepper's intrinsic width. The row was 1167px wide inside a 750px
  // column, its own overflow-x-auto never engaged, and the stage column scrolled
  // horizontally instead of the chevrons scrolling inside themselves.
  return (
    <div ref={ref} className="min-w-0 flex-1">
      {children}
    </div>
  );
}

function CondensedStages<Id extends string>({
  chrome,
  activeStage,
  position,
  total,
  previous,
  next,
  onSelectStage,
  shortcut,
}: {
  chrome: StageChrome<Id>;
  activeStage: Id;
  position: number;
  total: number;
  previous: Id | null;
  next: Id | null;
  onSelectStage: (id: Id) => void;
  shortcut: { id: Id; label: string; title: string } | null;
}) {
  return (
    // w-full, because this only ever appears beside the conversation panel and
    // the column it gets is already narrow. Hugging its content left a gap to
    // the right of a row that exists precisely because room is short.
    <div className="flex w-full items-center gap-2">
      <StepArrow
        chrome={chrome}
        direction="previous"
        target={previous}
        onSelectStage={onSelectStage}
      />
      <div className="min-w-0 flex-1 text-center">
        <p className="truncate text-[13px] font-semibold text-[color:var(--tp-ink)]">
          {chrome.meta[activeStage].heading}
        </p>
        <p className="tp-den">
          Stage {position} of {total}
        </p>
      </div>
      {/* The shortcut survives condensing, because this is the form the reader
          sees most: stepping to the gate one arrow at a time is six clicks. */}
      {shortcut && activeStage !== shortcut.id && (
        <button
          type="button"
          onClick={() => onSelectStage(shortcut.id)}
          title={shortcut.title}
          className="hidden shrink-0 rounded-lg border border-[color:var(--tp-line-strong)] px-2.5 py-1.5 text-[11px] font-semibold text-[color:var(--tp-ink-2)] transition-colors hover:border-blue-500/50 hover:text-blue-600 sm:block"
        >
          {shortcut.label}
        </button>
      )}
      <StepArrow chrome={chrome} direction="next" target={next} onSelectStage={onSelectStage} />
    </div>
  );
}

function StepArrow<Id extends string>({
  chrome,
  direction,
  target,
  onSelectStage,
}: {
  chrome: StageChrome<Id>;
  direction: "previous" | "next";
  target: Id | null;
  onSelectStage: (id: Id) => void;
}) {
  const Icon = direction === "previous" ? ChevronLeft : ChevronRight;
  return (
    <button
      type="button"
      disabled={!target}
      aria-label={
        target
          ? `${direction === "previous" ? "Previous" : "Next"}: ${chrome.meta[target].label}`
          : `No ${direction} stage`
      }
      title={target ? chrome.meta[target].label : undefined}
      onClick={() => target && onSelectStage(target)}
      className={cn(
        "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border transition-colors",
        target
          ? "border-[color:var(--tp-line-strong)] text-[color:var(--tp-ink-2)] hover:border-blue-500/50 hover:text-blue-600"
          : "cursor-default border-[color:var(--tp-line)] text-[color:var(--tp-muted)] opacity-40",
      )}
    >
      <Icon className="h-4 w-4" />
    </button>
  );
}

/* --------------------------------------------------------- section anchors */

function SectionAnchors({
  sections,
  activeSection,
}: {
  sections: StageSectionMeta[];
  activeSection: string | null;
}) {
  return (
    <>
      {/* Pills at desk width, one select on a phone: four pills plus the stage
          row would take the whole screen on a narrow viewport. */}
      {/* mt-3, not mt-2. Sitting one step below the chevrons these read as
          attached to them rather than as their own row, which matters most when
          the chevrons have collapsed to a single line beside the conversation. */}
      <div className="mt-3 hidden flex-wrap items-center gap-1.5 sm:flex">
        {sections.map((section) => (
          <button
            key={section.id}
            type="button"
            // Names the section this pill scrolls to, so the pair can be checked
            // against the order the page actually renders them in.
            data-section={section.id}
            aria-current={activeSection === section.id ? "location" : undefined}
            onClick={() => scrollToSection(section.id)}
            className={cn(
              "rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors",
              activeSection === section.id
                ? "border-blue-500/50 bg-blue-500/[0.08] text-blue-600 dark:text-blue-300"
                : "border-[color:var(--tp-line)] text-[color:var(--tp-ink-2)] hover:border-blue-500/40 hover:text-blue-600",
            )}
          >
            {section.label}
          </button>
        ))}
      </div>

      <label className="mt-2 block sm:hidden">
        <span className="sr-only">Jump to a section</span>
        <select
          value={activeSection ?? sections[0].id}
          onChange={(event) => scrollToSection(event.target.value)}
          className="w-full rounded-lg border border-[color:var(--tp-line)] bg-transparent px-2.5 py-1.5 text-[12px] text-[color:var(--tp-ink)] outline-none focus:border-blue-500/50"
        >
          {sections.map((section) => (
            <option key={section.id} value={section.id}>
              {section.label}
            </option>
          ))}
        </select>
      </label>
    </>
  );
}
