import type { Project, ProjectStatus } from "@/types/project";

/** Each status's phase, by the route segment its page lives under. */
const PHASE_OF: Record<ProjectStatus, "requirements" | "code" | "testing" | "deployment"> = {
  draft: "requirements",
  analyzing: "requirements",
  design: "requirements",
  code: "code",
  testing: "testing",
  deploy: "deployment",
  complete: "deployment",
};

/**
 * Where opening a project takes you: the phase its work is in.
 *
 * Every way into a project (Home, the list, the sidebar, the palette) landed on
 * Requirements and Design whatever its state, so a project waiting at its test
 * review opened three phases away from the decision it was waiting for. The
 * status is the server's, read from each phase's current version.
 */
export function projectHomePath(project: Pick<Project, "id" | "status">): string {
  return `/projects/${project.id}/${PHASE_OF[project.status] ?? "requirements"}`;
}
