import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { refreshProject } from "@/entities/project";
import type { DesignStageId } from "@/types/project";
import { codeKeys, requirementsKeys } from "@/lib/query";
import { requirementsApi } from "../api";
import type { DesignSnapshot, GateDecisionInput } from "../api/types";
import { regeneratingStageIds } from "../model/outdated";

/**
 * Reading and changing the design artifact.
 *
 * Every mutation answers with the whole snapshot, so each one ends the same way:
 * write it into the cache. There is no invalidation choreography to get wrong,
 * and no partial state for the UI to re-derive.
 */

/** Poll while work is in flight, and not one request after it finishes. */
const POLL_WHILE_GENERATING_MS = 1200;

export function useDesignSnapshot(projectId: string | null | undefined) {
  const id = projectId ?? "";
  return useQuery({
    queryKey: requirementsKeys.design(id),
    queryFn: () => requirementsApi.getDesign(id),
    enabled: Boolean(projectId),
    /**
     * The snapshot itself decides whether to keep asking.
     *
     * This replaces a ladder of fixed timeouts fired after each mutation, which
     * had to guess how long generation would take and stopped asking whether or
     * not it had finished. Six artifact families through a language model is a
     * minute or more, so no fixed ladder could be right. Polling only while a
     * stage says it is generating is both correct and quiet: it stops on its own.
     */
    refetchInterval: (query) => {
      const snapshot = query.state.data;
      if (!snapshot) return false;
      return regeneratingStageIds(snapshot).length > 0 ? POLL_WHILE_GENERATING_MS : false;
    },
  });
}

export function useDesignMutations(projectId: string) {
  const client = useQueryClient();
  const key = requirementsKeys.design(projectId);

  // The project's status and progress move with what the phase decides (an
  // approval moves it to Code), and the header and the lists read them.
  const commit = useCallback(
    (snapshot: DesignSnapshot) => {
      client.setQueryData(key, snapshot);
      void refreshProject(projectId).catch(() => {
        // A stale badge is the badge that was already on screen.
      });
    },
    [client, key, projectId],
  );

  const editRequirement = useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) =>
      requirementsApi.editRequirement(projectId, id, text),
    onSuccess: commit,
  });

  const editAssumption = useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) =>
      requirementsApi.editAssumption(projectId, id, text),
    onSuccess: commit,
  });

  const dismissAssumption = useMutation({
    mutationFn: ({ id, dismissed }: { id: string; dismissed: boolean }) =>
      requirementsApi.dismissAssumption(projectId, id, dismissed),
    onSuccess: commit,
  });

  const answerQuestion = useMutation({
    mutationFn: ({ id, answer }: { id: string; answer: string }) =>
      requirementsApi.answerQuestion(projectId, id, answer),
    onSuccess: commit,
  });

  const applyAnswers = useMutation({
    mutationFn: () => requirementsApi.applyAnswers(projectId),
    onSuccess: commit,
  });

  const continueFromQuestions = useMutation({
    mutationFn: (kind: "answers" | "assumptions") =>
      requirementsApi.continueFromQuestions(projectId, kind),
    onSuccess: commit,
  });

  const selectArchitecture = useMutation({
    mutationFn: ({ candidateId, by }: { candidateId: string; by: string }) =>
      requirementsApi.selectArchitecture(projectId, candidateId, by),
    onSuccess: commit,
  });

  const renameGraphNode = useMutation({
    mutationFn: ({ nodeId, label }: { nodeId: string; label: string }) =>
      requirementsApi.renameGraphNode(projectId, nodeId, label),
    onSuccess: commit,
  });

  const requestRefinement = useMutation({
    mutationFn: ({ flowId, note }: { flowId: string; note: string }) =>
      requirementsApi.requestWireframeRefinement(projectId, flowId, note),
    onSuccess: commit,
  });

  // Each of these can leave stages generating. None of them needs its own
  // timing: committing the snapshot is enough, because the query keeps asking
  // for as long as that snapshot says a stage is still being generated.
  const startDesignRun = useMutation({
    mutationFn: ({ text, files }: { text: string; files?: string[] }) =>
      requirementsApi.startDesignRun(projectId, text, files),
    onSuccess: commit,
  });

  const submitChange = useMutation({
    mutationFn: ({ note, by }: { note: string; by: string }) =>
      requirementsApi.submitChange(projectId, note, by),
    onSuccess: commit,
  });

  const retryStage = useMutation({
    mutationFn: (stageId: DesignStageId) => requirementsApi.retryStage(projectId, stageId),
    onSuccess: commit,
  });

  const startOver = useMutation({
    mutationFn: () => requirementsApi.startOver(projectId),
    onSuccess: commit,
  });

  const continueRun = useMutation({
    mutationFn: (runId: string) => requirementsApi.continueRun(projectId, runId),
    onSuccess: commit,
  });

  const submitGateDecision = useMutation({
    mutationFn: (decision: GateDecisionInput) =>
      requirementsApi.submitGateDecision(projectId, decision),
    onSuccess: (snapshot) => {
      commit(snapshot);
      // What Code Generation says it can start from moved with this decision,
      // and its page read again only once a minute while nothing generated.
      void client.invalidateQueries({ queryKey: codeKeys.snapshot(projectId) });
    },
  });

  return {
    startDesignRun,
    startOver,
    continueRun,
    editRequirement,
    editAssumption,
    dismissAssumption,
    answerQuestion,
    applyAnswers,
    continueFromQuestions,
    selectArchitecture,
    renameGraphNode,
    requestRefinement,
    submitChange,
    retryStage,
    submitGateDecision,
  };
}
