import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle, Download, Clock, RefreshCw } from "lucide-react";
import { Card, CardContent, Button } from "@/shared/ui/primitives";
import type { ActivityLogCategory, ActivityLogEntry } from "./fixtures/activityData";
import { useActivityLog } from "./hooks";
import { useUiStore } from "@/store/ui";
import { cn } from "@/shared/utils/cn";
import { PageLoader, PhaseSectionHeader, surface } from "@/shared/ui";
import { ActivityFilters, ActivityTimeline } from "./components";

/** One empty list for every render, so nothing downstream sees a new value. */
const NO_ENTRIES: ActivityLogEntry[] = [];

/** How many entries the server sends, newest first (its default). */
const ACTIVITY_LIMIT = 200;

export function ActivityLog() {
  const theme = useUiStore((s) => s.theme);
  const addToast = useUiStore((s) => s.addToast);
  const isDark = theme === "dark";
  const [filter, setFilter] = useState<ActivityLogCategory | "all">("all");
  const { projectId = "" } = useParams();
  const log = useActivityLog(projectId);
  const entries = log.data ?? NO_ENTRIES;

  const sortedEntries = useMemo(
    () =>
      [...entries].sort(
        (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
      ),
    [entries]
  );

  const filteredEntries = useMemo(
    () => (filter === "all" ? sortedEntries : sortedEntries.filter((e) => e.category === filter)),
    [sortedEntries, filter]
  );

  const handleExport = () => {
    const payload = filteredEntries.map(({ id, timestamp, title, description, actor, category, metric, artifactRef }) => ({
      id,
      timestamp,
      title,
      description,
      actor,
      category,
      metric,
      artifactRef,
    }));
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "activity-log.json";
    link.click();
    URL.revokeObjectURL(url);
    addToast({ type: "success", title: "Export complete", message: `${filteredEntries.length} entries exported` });
  };

  return (
    <div className="w-full space-y-5 p-4 sm:p-6 md:p-8">
      <PhaseSectionHeader
        title="Activity Log"
        subtitle="Complete project timeline from requirements through deployment"
        progress={0}
        isDark={isDark}
        showProgress={false}
        action={
          <Button variant="outline" size="sm" onClick={handleExport}>
            <Download className="h-3.5 w-3.5" />
            Export
          </Button>
        }
      />

      {log.isPending ? (
        <PageLoader label="Loading the activity" />
      ) : log.isError ? (
        <Card>
          <CardContent className="flex flex-wrap items-center gap-3 p-6">
            <AlertTriangle className="h-4 w-4 shrink-0 text-amber-500" />
            <p className="min-w-0 flex-1 text-sm">
              The activity log could not be read. Nothing was lost; it is the audit log, read again.
            </p>
            <Button variant="outline" size="sm" onClick={() => void log.refetch()}>
              <RefreshCw className="h-3.5 w-3.5" />
              Try again
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-6">
            <ActivityFilters filter={filter} onFilterChange={setFilter} isDark={isDark} />
            <ActivityTimeline entries={filteredEntries} isDark={isDark} />
          </CardContent>
        </Card>
      )}

      <div className={cn("flex flex-wrap items-center gap-4 rounded-xl border px-4 py-3 text-xs text-slate-500", surface.inset(isDark))}>
        <span className="flex items-center gap-1.5 font-medium">
          <Clock className="h-3.5 w-3.5" />
          {/* The server sends the newest 200; saying "total" claimed the rest. */}
          {sortedEntries.length >= ACTIVITY_LIMIT
            ? `The newest ${ACTIVITY_LIMIT} events`
            : `${sortedEntries.length} events`}
        </span>
        <span className={isDark ? "text-slate-400" : "text-slate-300"}>|</span>
        <span>From this project's audit log, read again every 15 seconds while open</span>
      </div>
    </div>
  );
}

/** @deprecated Use ActivityLog */
export const Traceability = ActivityLog;

export default ActivityLog;
