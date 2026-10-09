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
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0 flex-1">
        <h3 className={cn("text-xl font-semibold", isDark ? "text-white" : "text-slate-900")}>
          {title}
        </h3>
        <p className={cn("mt-1 text-sm", isDark ? "text-slate-400" : "text-slate-500")}>
          {subtitle}
        </p>
      </div>
      <div className="flex w-full shrink-0 flex-col items-stretch gap-3 sm:w-auto sm:items-end">
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
