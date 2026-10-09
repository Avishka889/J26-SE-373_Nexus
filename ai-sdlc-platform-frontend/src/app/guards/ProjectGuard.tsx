import type { ReactNode } from "react";
import { Navigate, useParams } from "react-router-dom";
import { hydrateProjects, useProject, useProjectsLoad } from "@/entities/project";
import { ServerUnavailable } from "@/shared/ui/ServerUnavailable";
import { PageLoader } from "@/shared/ui/Spinner";

export function ProjectGuard({ children }: { children: ReactNode }) {
  const { projectId } = useParams();
  const load = useProjectsLoad();
  const project = useProject(projectId);

  // The list first. With projects live it starts empty, so asking "is this
  // project real" before the first read answers no for every project, and a deep
  // link bounced to the list every time; a read that failed is said so, with a
  // retry, rather than leaving the page empty for good.
  if (load.status === "loading") return <PageLoader label="Loading the project" />;
  if (load.status === "failed") {
    return (
      <div className="p-4 sm:p-6 md:p-8">
        <ServerUnavailable
          title="This project could not be loaded"
          message={load.error ?? ""}
          onRetry={hydrateProjects}
        />
      </div>
    );
  }
  if (!project) {
    // Said, not silent: the list explains that the project is gone, rather
    // than a shared link appearing to open the list for no reason.
    return <Navigate to="/projects" replace state={{ missing: projectId }} />;
  }
  return <>{children}</>;
}
