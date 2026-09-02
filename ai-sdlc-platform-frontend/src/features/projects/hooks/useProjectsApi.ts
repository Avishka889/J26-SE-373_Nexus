import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { projectKeys } from "@/lib/query";
import type { Project, RequirementChatMessage } from "@/types/project";
import {
  projectsApi,
  useProjectsList,
  useProject,
} from "@/entities/project";

export { useProjectsList, useProject };

export function useProjectsQuery() {
  return useQuery({
    queryKey: projectKeys.all,
    queryFn: () => projectsApi.list(),
  });
}

export function useProjectMutations() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: projectKeys.all });

  const createProject = useMutation({
    mutationFn: ({ name, description }: { name: string; description?: string }) =>
      projectsApi.create(name, description),
    onSuccess: invalidate,
  });

  const updateProject = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<Project> }) =>
      projectsApi.update(id, patch),
    onSuccess: invalidate,
  });

  const deleteProject = useMutation({
    mutationFn: (id: string) => projectsApi.delete(id),
    onSuccess: invalidate,
  });

  const appendRequirementChatMessage = useMutation({
    mutationFn: ({
      projectId,
      message,
    }: {
      projectId: string;
      message: Omit<RequirementChatMessage, "id" | "createdAt">;
    }) => projectsApi.appendRequirementChatMessage(projectId, message),
    onSuccess: invalidate,
  });

  return {
    createProject,
    updateProject,
    deleteProject,
    appendRequirementChatMessage,
    updateProjectSync: (id: string, patch: Partial<Project>) => projectsApi.update(id, patch),
    appendChatSync: (
      projectId: string,
      message: Omit<RequirementChatMessage, "id" | "createdAt">,
    ) => projectsApi.appendRequirementChatMessage(projectId, message),
    createProjectSync: (
      name: string,
      description?: string,
      requirementText?: string,
      files?: string[],
    ) => projectsApi.create(name, description, requirementText, files),
    deleteProjectSync: (id: string) => projectsApi.delete(id),
  };
}
