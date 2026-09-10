import { useEffect } from "react";
import { Navigate, useParams } from "react-router-dom";
import { useSessionStore } from "@/store/session";
import { useUiStore } from "@/store/ui";
import { logger } from "@/lib/logger";
import { hydrateProjects, useProject } from "@/entities/project";
import { PageLoader } from "@/shared/ui/Spinner";
import { useDesignMutations, useDesignSnapshot } from "./hooks/useDesign";
import { RequirementsInput } from "./components/RequirementsInput";
import { DesignWorkspace } from "./components/DesignWorkspace";
import { messageOf } from "@/lib/http";
import { readState } from "@/shared/ui/phase";
import { ServerUnavailable } from "@/shared/ui/ServerUnavailable";

/**
 * Which of the two screens this phase shows.
 *
 * The answer comes from the design snapshot, not from `project.reqPhase`: a
 * second copy of the same fact is how the phase came to show four disagreeing
 * status claims at once. Version 0 means nothing has been generated, so the
 * input is what belongs on screen.
 */
export function RequirementsPage() {
  const { projectId = "" } = useParams();
  const project = useProject(projectId);
  const query = useDesignSnapshot(projectId);
  const { startDesignRun } = useDesignMutations(projectId);
  const setActiveProjectId = useSessionStore((s) => s.setActiveProjectId);
  const setConversationOpen = useUiStore((s) => s.setConversationOpen);

  useEffect(() => {
    if (project) setActiveProjectId(project.id);
  }, [project, setActiveProjectId]);

  const started = (query.data?.requirementsVersion ?? 0) > 0;
  const carriedText = project?.requirementText.trim() ?? "";

  /**
   * Requirement text that arrived with the project starts the run by itself.
   *
   * This is the same rule the orchestrator uses: text going from empty to non
   * empty is the start signal, and there is no separate call meaning "now begin".
   * It is what lets the home composer hand its text over and navigate here
   * without knowing anything about design stages.
   */
  useEffect(() => {
    if (!query.data || started || !carriedText) return;
    if (!startDesignRun.isIdle) return;
    setConversationOpen(false);
    startDesignRun.mutate({ text: carriedText, files: project?.files ?? [] });
  }, [query.data, started, carriedText, startDesignRun, project?.files, setConversationOpen]);

  /**
   * The run can rename the project, so the store has to be told.
   *
   * Triggered by the two names disagreeing rather than by watching a stage
   * flip. Comparing them is self correcting: refetching is what removes the
   * disagreement, so this cannot loop, and it needs no memory of which poll was
   * the first one to see the new name. A refetch that fails leaves the
   * provisional name in place on purpose: it is already a reasonable name, so
   * this is logged rather than surfaced, not worth a toast the reader did not
   * ask for.
   */
  useEffect(() => {
    const titled = query.data?.appName;
    if (!titled || !project || titled === project.name) return;
    hydrateProjects().catch((error: unknown) => {
      logger.warn("Could not refetch projects after a run rename", {
        projectId: project.id,
        name: error instanceof Error ? error.name : "UnknownError",
        message: error instanceof Error ? error.message : String(error),
      });
    });
  }, [query.data?.appName, project?.name]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!project) return <Navigate to="/projects" replace />;

  if (query.isPending) {
    return (
      <div className="tp w-full p-4 sm:p-6 md:p-8">
        <PageLoader label="Loading the design" />
      </div>
    );
  }

  // Before "not started": with the first read failed there is no version to
  // read, and taking that for "no design yet" offered the start screen over a
  // project that had one, whose submit rewrote the stored brief.
  if (readState(query) === "failed") {
    return (
      <div className="tp w-full p-4 sm:p-6 md:p-8">
        <ServerUnavailable
          title="This design could not be loaded"
          message={messageOf(query.error)}
          onRetry={() => query.refetch()}
        />
      </div>
    );
  }

  if (!started) {
    return (
      <RequirementsInput
        project={project}
        isStarting={startDesignRun.isPending}
        onSubmit={(text, files) => {
          // The stages come first while the run fills them; the conversation
          // opens from its toggle, which counts the questions waiting.
          setConversationOpen(false);
          startDesignRun.mutate({ text, files });
        }}
      />
    );
  }

  return <DesignWorkspace project={project} />;
}

export function Page() {
  return <RequirementsPage />;
}

export default RequirementsPage;
