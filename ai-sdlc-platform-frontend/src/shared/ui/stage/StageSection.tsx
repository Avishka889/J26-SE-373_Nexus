import type { ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import { nextStageIn, type StageChrome } from "./types";

/**
 * A block of a stage that an anchor can point at.
 *
 * The id is the anchor target and the scroll spy's subject, and `tp-anchor` is
 * what stops it landing behind the sticky chrome. Wrapping rather than passing
 * an id into each panel keeps the two lists (what a stage renders, what its
 * anchors name) impossible to get out of step, because they are the same id.
 */
export function StageSection({
  id,
  children,
  className,
}: {
  id: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={`tp-anchor ${className ?? ""}`}>
      {children}
    </section>
  );
}

/**
 * The way on from the bottom of a stage.
 *
 * Eight stages with no forward path read as eight separate pages that happen to
 * share a header. This makes them one route, and the last one leads to the
 * decision rather than to nothing.
 */
export function StageFooterNav<Id extends string>({
  chrome,
  stageId,
  onSelectStage,
}: {
  chrome: StageChrome<Id>;
  stageId: Id;
  onSelectStage: (id: Id) => void;
}) {
  const next = nextStageIn(chrome, stageId);
  if (!next) return null;

  return (
    <div className="flex justify-end pt-1">
      <button
        type="button"
        onClick={() => onSelectStage(next)}
        className="group inline-flex items-center gap-2 rounded-xl border border-[color:var(--tp-line-strong)] px-4 py-2.5 text-[13px] font-medium text-[color:var(--tp-ink)] transition-colors hover:border-blue-500/50 hover:text-blue-600"
      >
        <span className="tp-den">Next</span>
        {chrome.meta[next].label}
        <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
      </button>
    </div>
  );
}
