import { useEffect, useRef, useSyncExternalStore } from "react";
import type { Project } from "@/types/project";
import {
  projectsApi,
  refreshProject,
  subscribeProjects,
  getProjectsSnapshot,
  getProjectsLoad,
  type ProjectsLoad,
} from "./api";

export function useProjectsList(): Project[] {
  return useSyncExternalStore(subscribeProjects, getProjectsSnapshot, getProjectsSnapshot);
}

/**
 * Where the first read of the project list stands: on its way, read, or failed
 * with a reason. A route guard and the lists need all three, because "still
 * loading", "could not be read" and "no projects" each look different.
 */
export function useProjectsLoad(): ProjectsLoad {
  return useSyncExternalStore(subscribeProjects, getProjectsLoad, getProjectsLoad);
}

export function useProject(id: string | null | undefined): Project | undefined {
  const projects = useProjectsList();
  if (!id) return undefined;
  return projects.find((p) => p.id === id);
}

/**
 * Keep a project's row in step with its phase's run.
 *
 * Status, progress and, on a first run, the name change on the server while a
 * run works, and only Design and Code asked again: after a testing or a
 * deployment run the header and the lists kept the status from before it.
 * Tied to the phase's busy flag rather than polled, so it costs two reads per
 * run, one as it starts and one as it settles. `busy` is undefined until the
 * phase has been read.
 */
export function useProjectFollowsItsRun(projectId: string | null | undefined, busy: boolean | undefined) {
  // The effect runs only when `busy` changes, which is exactly a run starting
  // or settling, plus once when the phase is first read.
  const read = useRef(false);
  useEffect(() => {
    if (!projectId || busy === undefined) return;
    const first = !read.current;
    read.current = true;
    // Opening a phase that is idle changes nothing worth a read.
    if (first && !busy) return;
    void refreshProject(projectId).catch(() => {
      // A stale badge is the badge that was already on screen.
    });
  }, [projectId, busy]);
}

export { projectsApi };
