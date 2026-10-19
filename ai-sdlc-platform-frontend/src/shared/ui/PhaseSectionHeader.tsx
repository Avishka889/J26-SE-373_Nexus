import type { ReactNode } from "react";
import { cn } from "@/shared/utils/cn";
import { Progress } from "./primitives";

/** Presentational phase header. Each phase passes its own progress in. */
export function PhaseSectionHeader({
  title,
  subtitle,
  progress,
  isDark,
  action,
  showProgress = true,
  valueLabel,
  roomyTitle = false,
}: {
  title: string;
  subtitle: string;
  progress: number;
  isDark: boolean;
  action?: ReactNode;
  showProgress?: boolean;
  /**
   * Replaces the percentage when a phase is judged on something other than a
   * number, for example a gate that is generated but not yet approved.
   */
  valueLabel?: string;
  /**
   * Gives the title a width of its own, so a wide action wraps under it and
   * does not squeeze it. Testing's action is a selector and a button: beside
   * them the blurb ran to four lines in a column a quarter of the page wide.
   */
  roomyTitle?: boolean;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className={cn("min-w-0 flex-1", roomyTitle && "basis-[26rem]")}>
        <h3 className={cn("text-xl font-semibold", isDark ? "text-white" : "text-slate-900")}>
          {title}
        </h3>
        <p className={cn("mt-1 text-sm", isDark ? "text-slate-400" : "text-slate-500")}>
          {subtitle}
        </p>
      </div>
      {/* May shrink, and never wider than the header. It was `shrink-0`, so it
          took its action's widest possible line as its width: 808px inside a
          650px column on a 1366 laptop, with the progress bar and the run
          button cut off at the edge. `ml-auto` keeps it to the right when it
          wraps onto a line of its own. */}
      <div className="ml-auto flex w-full min-w-0 max-w-full flex-col items-stretch gap-3 sm:w-auto sm:items-end">
        {showProgress && (
          <div className="w-full sm:w-48">
            <div className="mb-1 flex justify-between text-xs">
              <span className={isDark ? "text-slate-400" : "text-slate-500"}>Progress</span>
              <span className={cn("font-medium tabular-nums", isDark ? "text-white" : "text-slate-900")}>
                {valueLabel ?? `${progress}%`}
              </span>
            </div>
            <Progress value={progress} color="#2563eb" />
          </div>
        )}
        {action}
      </div>
    </div>
  );
}
