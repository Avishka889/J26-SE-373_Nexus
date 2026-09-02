import type { ActivityLogEntry } from "../fixtures/activityData";
import { cn } from "@/shared/utils/cn";
import { TimelineEntry } from "./TimelineEntry";

export function ActivityTimeline({
  entries,
  isDark,
}: {
  entries: ActivityLogEntry[];
  isDark: boolean;
}) {
  if (entries.length === 0) {
    return (
      <div className={cn("py-12 text-center text-sm", isDark ? "text-slate-400" : "text-slate-500")}>
        No activity entries for this filter.
      </div>
    );
  }

  return (
    <div className="relative">
      {entries.map((entry, i) => (
        <TimelineEntry
          key={entry.id}
          entry={entry}
          isDark={isDark}
          isLast={i === entries.length - 1}
        />
      ))}
    </div>
  );
}
