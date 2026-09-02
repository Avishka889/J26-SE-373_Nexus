import { isLive } from "@/lib/env";
import { http } from "@/lib/http";
import {
  activityLogEntries,
  type ActivityLogEntry,
} from "../fixtures/activityData";

export interface ActivityApi {
  /** One project's events, newest first, from the audit log. */
  list(projectId: string): Promise<ActivityLogEntry[]>;
}

function createFixtureActivityApi(): ActivityApi {
  return {
    // The demo's entries belong to no project in particular, so every demo
    // project shows them.
    async list() {
      return structuredClone(activityLogEntries);
    },
  };
}

function createHttpActivityApi(): ActivityApi {
  return {
    list: (projectId) =>
      http.get<ActivityLogEntry[]>(`/activity?project=${encodeURIComponent(projectId)}`),
  };
}

export const activityApi: ActivityApi = isLive("activity")
  ? createHttpActivityApi()
  : createFixtureActivityApi();
