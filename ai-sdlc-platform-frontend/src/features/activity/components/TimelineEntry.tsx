import {
  CheckCircle2,
  RotateCcw,
  XCircle,
  FileText,
  Pencil,
  Code2,
  FlaskConical,
  ShieldAlert,
  Rocket,
  CheckCheck,
  SlidersHorizontal,
} from "lucide-react";
import { Badge } from "@/shared/ui/primitives";
import type {
  ActivityLogCategory,
  ActivityLogEntry,
} from "../fixtures/activityData";
import { cn } from "@/shared/utils/cn";
import { formatWhen } from "@/shared/utils/time";

const categoryConfig: Record<
  ActivityLogCategory,
  { icon: typeof CheckCircle2; iconBg: string; label: string }
> = {
  requirement: { icon: FileText, iconBg: "bg-blue-600", label: "Requirements" },
  design: { icon: Pencil, iconBg: "bg-blue-600", label: "Design" },
  code: { icon: Code2, iconBg: "bg-blue-600", label: "Code" },
  testing: { icon: FlaskConical, iconBg: "bg-amber-500", label: "Testing" },
  security: { icon: ShieldAlert, iconBg: "bg-amber-500", label: "Security" },
  deployment: { icon: Rocket, iconBg: "bg-emerald-500", label: "Deployment" },
  approval: { icon: CheckCheck, iconBg: "bg-emerald-500", label: "Approval" },
  settings: {
    icon: SlidersHorizontal,
    iconBg: "bg-slate-500",
    label: "Settings",
  },
};

/**
 * The server can grow a category before this map learns it. An unknown one
 * renders as itself with a neutral mark rather than crashing the feed on
 * `categoryConfig[category].icon`.
 */
function configFor(category: ActivityLogCategory) {
  return (
    categoryConfig[category] ?? {
      icon: CheckCircle2,
      iconBg: "bg-slate-500",
      label: category,
    }
  );
}

/** How the event went, as the server read it from its action: the mark it draws. */
const outcomeConfig: Record<
  NonNullable<ActivityLogEntry["outcome"]>,
  { icon: typeof CheckCircle2; iconBg: string; label: string } | null
> = {
  failed: { icon: XCircle, iconBg: "bg-red-500", label: "Failed" },
  changes: { icon: RotateCcw, iconBg: "bg-amber-500", label: "Changes requested" },
  done: { icon: CheckCircle2, iconBg: "bg-emerald-500", label: "Succeeded" },
  info: null,
};

const metricToneStyles = {
  success: "text-emerald-700 dark:text-emerald-400",
  warning: "text-amber-700 dark:text-amber-400",
  error: "text-red-600 dark:text-red-400",
  neutral: "text-slate-900 dark:text-slate-100",
};

export function TimelineEntry({
  entry,
  isDark,
  isLast,
}: {
  entry: ActivityLogEntry;
  isDark: boolean;
  isLast: boolean;
}) {
  // The mark is how the event went when the server said, and the phase's own
  // mark otherwise. It came from the category alone, so a change request at a
  // review drew the green check, and a failed run the Design pencil.
  const config = configFor(entry.category);
  const outcome = entry.outcome ? outcomeConfig[entry.outcome] : null;
  const iconBg = outcome?.iconBg ?? config.iconBg;
  const DisplayIcon = outcome?.icon ?? config.icon;

  return (
    <div className="relative flex gap-4 pb-8 last:pb-0">
      {!isLast && (
        <div
          className={cn(
            "absolute left-4 top-8 w-px -translate-x-1/2",
            isDark ? "bg-slate-700" : "bg-slate-200",
          )}
          style={{ height: "calc(100% - 8px)" }}
        />
      )}

      <div
        className={cn(
          "relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          iconBg,
        )}
      >
        <DisplayIcon className="h-4 w-4 text-white" aria-hidden="true" />
        {outcome && <span className="sr-only">{outcome.label}</span>}
      </div>

      <div className="flex min-w-0 flex-1 items-start justify-between gap-4 pt-0.5">
        <div className="min-w-0 space-y-1">
          <h4
            className={cn(
              "break-words text-sm font-semibold",
              isDark ? "text-white" : "text-slate-900",
            )}
          >
            {entry.title}
          </h4>
          <p
            className={cn(
              "text-sm leading-relaxed [overflow-wrap:anywhere]",
              isDark ? "text-slate-400" : "text-slate-500",
            )}
          >
            {entry.description}
          </p>
          {entry.metric && (
            <p
              className={cn(
                "text-sm font-semibold",
                metricToneStyles[entry.metricTone ?? "neutral"],
              )}
            >
              {entry.metric}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Badge variant="default">{config.label}</Badge>
            <span
              className={cn(
                "text-xs",
                isDark ? "text-slate-400" : "text-slate-500",
              )}
            >
              {entry.actor}
            </span>
            {entry.artifactRef && (
              <span
                className={cn(
                  "font-mono text-[10px]",
                  isDark ? "text-slate-400" : "text-slate-500",
                )}
              >
                {entry.artifactRef}
              </span>
            )}
          </div>
        </div>
        <time
          dateTime={entry.timestamp}
          className={cn(
            "shrink-0 text-sm",
            isDark ? "text-slate-400" : "text-slate-500",
          )}
        >
          {formatWhen(entry.timestamp)}
        </time>
      </div>
    </div>
  );
}
