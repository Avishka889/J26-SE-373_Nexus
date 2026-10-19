/**
 * Multi-page feature: route screens live in `pages/`.
 * Shared UI (e.g. ProjectCreatePrompt) stays in `components/`.
 * Default export is the Projects list (primary page).
 */
export { Home, Projects, NewProject } from "./pages";
export { Projects as Page } from "./pages";
export { default } from "./pages/Projects";
export { useProjectsList, useProject, useProjectsQuery, useProjectMutations } from "./hooks";
