import type { ReactNode } from "react";
import { CircleDot, X } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import {
  deriveStepStatuses,
  isStepDisabled,
  type StepStatus,
  type StepperStep,
} from "@/shared/ui/chevronStatus";
import { Spinner } from "./Spinner";

function chevronClip(isFirst: boolean, isLast: boolean) {
  const tip = 10;
  if (isFirst && isLast) return undefined;
  if (isFirst) return `polygon(0 0, calc(100% - ${tip}px) 0, 100% 50%, calc(100% - ${tip}px) 100%, 0 100%)`;
  if (isLast) return `polygon(0 0, 100% 0, 100% 100%, 0 100%, ${tip}px 50%)`;
  return `polygon(0 0, calc(100% - ${tip}px) 0, 100% 50%, calc(100% - ${tip}px) 100%, 0 100%, ${tip}px 50%)`;
}

// The 700 shades: white on emerald-500 was 2.5:1, on amber-400 1.7:1 and on
// red-500 3.8:1, below the 4.5:1 a label needs. These are 5:1 or better.
const statusStyles: Record<StepStatus, string> = {
  complete: "bg-emerald-700 text-white",
  pending: "bg-amber-700 text-white",
  generating: "bg-amber-700 text-white",
  failed: "bg-red-700 text-white",
  future: "bg-slate-200 text-slate-600",
};

const darkStatusStyles: Record<StepStatus, string> = {
  complete: "bg-emerald-700 text-white",
  pending: "bg-amber-700 text-white",
  generating: "bg-amber-700 text-white",
  failed: "bg-red-700 text-white",
  future: "bg-slate-700/60 text-slate-300",
};

/**
 * A stage's state in words, for a screen reader and the tooltip: colour alone
 * said it before. On screen a waiting stage carries a dot, a failed one a cross
 * and a generating one a spinner; complete, the common case, carries nothing, so
 * the row of eight still fits beside the page.
 */
const STATUS_WORDS: Record<StepStatus, string> = {
  complete: "complete",
  pending: "waiting",
  generating: "generating",
  failed: "failed",
  future: "not reached yet",
};

export function ChevronStepper({
  steps,
  currentId,
  progressId,
  selectedId,
  isDark = false,
  onStepClick,
}: {
  /** `badgeLabel` is what the badge counts, read in place of the bare number. */
  steps: (StepperStep & { badge?: ReactNode; badgeLabel?: string })[];
  currentId?: string;
  progressId?: string;
  selectedId?: string | null;
  isDark?: boolean;
  onStepClick?: (id: string) => void;
}) {
  const statuses = deriveStepStatuses(steps, progressId, currentId);

  return (
    <div
      className={cn(
        "flex gap-1 overflow-x-auto rounded-xl border p-1.5 scrollbar-none sm:p-2",
        "snap-x snap-mandatory",
        isDark ? "border-white/10 bg-white/[0.03]" : "border-slate-200/80 bg-white shadow-sm"
      )}
    >
      {steps.map((step, i) => {
        const isFirst = i === 0;
        const isLast = i === steps.length - 1;
        const status = statuses[i];
        const disabled = !onStepClick || isStepDisabled(status);

        return (
          <button
            key={step.id}
            type="button"
            onClick={() => onStepClick?.(step.id)}
            disabled={disabled}
            aria-current={selectedId === step.id ? "step" : undefined}
            title={`${step.label}: ${STATUS_WORDS[status]}`}
            className={cn(
              // Grow to fill the row, but never shrink below the label: the chevron
              // is clipped to a polygon, so a shrunk button cuts its own text off
              // rather than ellipsing it. When labels genuinely do not fit, the
              // row scrolls, which it is already set up to do.
              // Relative, so the status words a screen reader hears are placed
              // inside the chevron: positioned against an outer box, they sat
              // past the row's own scroll and widened the whole stage column.
              "relative flex min-w-[76px] flex-[1_0_auto] snap-start items-center justify-center whitespace-nowrap px-2.5 py-2 text-[11px] font-semibold tracking-wide transition-opacity sm:min-w-[88px] sm:px-4 sm:py-2.5 sm:text-xs",
              isDark ? darkStatusStyles[status] : statusStyles[status],
              // Darker on hover, not fainter: fading the fill took white text below 4.5:1.
              !disabled && "cursor-pointer hover:brightness-90",
              disabled && "cursor-default",
              selectedId === step.id && "ring-2 ring-blue-500 ring-offset-1",
              isDark && selectedId === step.id && "ring-offset-[#071018]"
            )}
            style={{
              clipPath: chevronClip(isFirst, isLast),
              zIndex: steps.length - i,
            }}
          >
            {status === "generating" && <Spinner size="xs" decorative className="mr-1.5" />}
            {status === "failed" && <X aria-hidden="true" className="mr-1 h-3.5 w-3.5 shrink-0" />}
            {status === "pending" && <CircleDot aria-hidden="true" className="mr-1 h-3.5 w-3.5 shrink-0" />}
            {step.label}
            <span className="sr-only">, {STATUS_WORDS[status]}</span>
            {step.badge != null && step.badgeLabel && (
              <span className="sr-only">, {step.badgeLabel}</span>
            )}
            {step.badge != null && (
              <span
                aria-hidden={step.badgeLabel ? true : undefined}
                className={cn(
                  "ml-1.5 inline-flex min-w-[17px] items-center justify-center rounded-full px-1.5 py-px text-[10px] font-bold leading-4",
                  status === "future"
                    ? isDark
                      ? "bg-white/10 text-slate-300"
                      : "bg-slate-900/10 text-slate-600"
                    : "bg-white/25 text-white"
                )}
              >
                {step.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
