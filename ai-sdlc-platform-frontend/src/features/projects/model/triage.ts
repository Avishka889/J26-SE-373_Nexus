import type { Project } from "@/types/project";

/** Which projects the list shows: by the phase a project is in, or stopped. */
export type StatusFilter = "all" | "design" | "code" | "testing" | "deploy" | "complete" | "stopped";
export type SortOrder = "newest" | "updated" | "name";

export const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All projects" },
  { value: "design", label: "In Requirements and Design" },
  { value: "code", label: "In Code Generation" },
  { value: "testing", label: "In Testing and Security" },
  { value: "deploy", label: "In Deployment" },
  { value: "complete", label: "Complete" },
  { value: "stopped", label: "Stopped" },
];

export const SORT_ORDERS: { value: SortOrder; label: string }[] = [
  { value: "newest", label: "Newest first" },
  { value: "updated", label: "Recently updated" },
  { value: "name", label: "Name, A to Z" },
];

const IN_DESIGN = new Set<Project["status"]>(["draft", "analyzing", "design"]);

function shows(project: Project, status: StatusFilter): boolean {
  if (status === "all") return true;
  if (status === "stopped") return Boolean(project.runStopped);
  if (status === "design") return IN_DESIGN.has(project.status);
  return project.status === status;
}

/**
 * The projects to list, matched, filtered and ordered.
 *
 * With eighty projects there was no way to find the ones waiting at a phase or
 * stopped, or to order them other than by when they were made.
 */
export function triage(
  projects: readonly Project[],
  { query, status, sort }: { query: string; status: StatusFilter; sort: SortOrder },
): Project[] {
  const needle = query.trim().toLowerCase();
  const kept = projects.filter(
    (p) =>
      shows(p, status) &&
      (!needle ||
        p.name.toLowerCase().includes(needle) ||
        p.description.toLowerCase().includes(needle) ||
        p.requirementText.toLowerCase().includes(needle)),
  );
  const time = (value: string) => new Date(value).getTime() || 0;
  return [...kept].sort((a, b) =>
    sort === "name"
      ? a.name.localeCompare(b.name, undefined, { sensitivity: "base" })
      : sort === "updated"
        ? time(b.updatedAt) - time(a.updatedAt)
        : time(b.createdAt) - time(a.createdAt),
  );
}
