import { useEffect } from "react";
import { Navigate, useParams } from "react-router-dom";
import { useSessionStore } from "@/store/session";
import { useProject } from "@/entities/project";
import { CodeWorkspace } from "./components/CodeWorkspace";

/**
 * The Code Generation route.
 *
 * The route parameter wins over the session's active project, which is a fix
 * rather than a preference: reading `activeProjectId ?? projectId` meant
 * opening this phase from a link showed whichever project was last visited,
 * and the URL and the content disagreed with no way for the reader to tell.
 *
 * There is no second screen the way Requirements has an input: a code phase
 * with nothing generated is still this workspace, saying so. Generation starts
 * from a button, never from arriving, because a run costs minutes and money.
 */
export function CodeGeneration() {
  const { projectId = "" } = useParams();
  const project = useProject(projectId);
  const setActiveProjectId = useSessionStore((s) => s.setActiveProjectId);

  useEffect(() => {
    if (project) setActiveProjectId(project.id);
  }, [project, setActiveProjectId]);

  if (!project) return <Navigate to="/projects" replace />;

  return <CodeWorkspace project={project} />;
}

export function Page() {
  return <CodeGeneration />;
}

export default CodeGeneration;
