import { useQuery } from "@tanstack/react-query";
import { activityKeys } from "@/lib/query";
import { activityApi } from "../api";

/**
 * One project's activity, read as every other phase reads its data.
 *
 * It was a hand made store that fetched once when the module loaded and handed
 * React `cache ?? []`: a new empty list on every read until the log arrived.
 * React compares consecutive snapshots, saw a change on every read, and
 * rendered until it gave up ("Maximum update depth exceeded"), so the page
 * crashed on every live visit and a failed request left it that way.
 */
export function useActivityLog(projectId: string) {
  return useQuery({
    queryKey: activityKeys.list(projectId),
    queryFn: () => activityApi.list(projectId),
    enabled: Boolean(projectId),
    // Read again while the page is open: it never refreshed during a run, so
    // the events of a run in progress appeared only on a reload.
    refetchInterval: 15_000,
  });
}
