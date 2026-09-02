import { useNavigate } from "react-router-dom";
import { projectDescription, projectName } from "@/entities/project";
import { useUiStore } from "@/store/ui";
import { useProjectMutations } from "./useProjectsApi";

/**
 * Create a project from the prompt, and open its design with the conversation closed.
 *
 * The run fills the stages first, and they are what a reader watches while it
 * does. Open, the conversation took its column from them the moment a project
 * began; it opens from its toggle, which counts the questions waiting, when there
 * is something to answer. Home and New project both start here.
 */
export function useCreateFromPrompt() {
  const navigate = useNavigate();
  const addToast = useUiStore((s) => s.addToast);
  const setConversationOpen = useUiStore((s) => s.setConversationOpen);
  const { createProjectSync } = useProjectMutations();

  return async (text: string, files: string[], typed: string) => {
    const name = projectName(typed, files);
    const project = await createProjectSync(name, projectDescription(typed, files), text, files);
    setConversationOpen(false);
    addToast({ type: "success", title: "Project created", message: name });
    navigate(`/projects/${project.id}/requirements`);
  };
}
