import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { refreshProject } from "@/entities/project";
import { codeKeys } from "@/lib/query";
import type { CodeStageId } from "@/types/project";
import { codeApi } from "../api";
import type { CodeDecisionInput, CodeSnapshot } from "../api/types";
import { generatingCodeStageIds } from "../model/outdated";

/**
 * Reading and changing the code artefact.
 *
 * Every mutation answers with the whole snapshot, so each one ends the same
 * way: write it into the cache. There is no invalidation choreography to get
 * wrong, and no partial state for the UI to re-derive.
 */

/** Poll while work is in flight, and not one request after it finishes. */
const POLL_WHILE_GENERATING_MS = 1200;
/** One read a minute while the page is open and nothing generates. */
const POLL_WHILE_OPEN_MS = 60_000;

export function useCodeSnapshot(projectId: string | null | undefined) {
  const id = projectId ?? "";
  return useQuery({
    queryKey: codeKeys.snapshot(id),
    queryFn: () => codeApi.getCode(id),
    enabled: Boolean(projectId),
    // Read afresh whenever the page opens, Continue from an approved design
    // included: a snapshot younger than the cache's thirty seconds could
    // predate the approval, and the page said the design "is being
    // regenerated" until its next read a minute later.
    refetchOnMount: "always",
    /**
     * The snapshot itself decides whether to keep asking. Generating a
     * monorepo is minutes rather than seconds, so no fixed ladder of timeouts
     * could be right; polling only while a stage says it is generating is both
     * correct and quiet, because it stops on its own.
     */
    refetchInterval: (query) => {
      const snapshot = query.state.data;
      if (!snapshot) return false;
      // And slowly while the page is open: a fix Testing applies is a new code
      // version, and the page kept showing the old one until it was left.
      return generatingCodeStageIds(snapshot).length > 0
        ? POLL_WHILE_GENERATING_MS
        : POLL_WHILE_OPEN_MS;
    },
  });
}

/** One generated file, fetched only when a reader opens it. */
export function useCodeFile(projectId: string, path: string | null, version: number) {
  return useQuery({
    queryKey: codeKeys.file(projectId, path ?? "", version),
    queryFn: () => codeApi.getFile(projectId, path ?? "", version),
    enabled: Boolean(projectId && path),
    // A file at a version never changes: the run that wrote it is finished.
    staleTime: Infinity,
  });
}

/** What a version changed since the one before it, for the review (C2-8). */
export function useCodeChanges(projectId: string, version: number) {
  return useQuery({
    queryKey: codeKeys.changes(projectId, version),
    queryFn: () => codeApi.getChanges(projectId, version),
    enabled: Boolean(projectId && version > 0),
    // Two finished versions do not change.
    staleTime: Infinity,
  });
}

export function useCodeMutations(projectId: string) {
  const client = useQueryClient();
  const key = codeKeys.snapshot(projectId);

  const commit = useCallback(
    (snapshot: CodeSnapshot) => {
      client.setQueryData(key, snapshot);
      // The project's status and progress move with the code phase, and the
      // header and the sidebar read them. Cheap, and only on a change.
      void refreshProject(projectId).catch(() => {
        // A stale badge is the badge that was already on screen. Nothing here
        // is worth interrupting a run for.
      });
    },
    [client, key, projectId],
  );

  const generate = useMutation({
    mutationFn: (supersede: boolean = false) => codeApi.generate(projectId, supersede),
    onSuccess: commit,
    // The workspace says why generation could not start, in its own toast.
    meta: { reportsOwnErrors: true },
  });

  const setStoryScope = useMutation({
    mutationFn: ({
      storyId,
      inScope,
      by,
      supersede,
    }: {
      storyId: string;
      inScope: boolean;
      by: string;
      supersede: boolean;
    }) => codeApi.setStoryScope(projectId, storyId, inScope, by, supersede),
    onSuccess: commit,
  });

  const planNextSprint = useMutation({
    mutationFn: ({ by, supersede }: { by: string; supersede: boolean }) =>
      codeApi.planNextSprint(projectId, by, supersede),
    onSuccess: commit,
  });

  const selectStack = useMutation({
    mutationFn: ({ stackId, by }: { stackId: string; by: string }) =>
      codeApi.selectStack(projectId, stackId, by),
    onSuccess: commit,
  });

  const chooseArm = useMutation({
    mutationFn: ({
      arm,
      by,
      supersede,
    }: {
      arm: "rule" | "llm" | "merged";
      by: string;
      supersede: boolean;
    }) => codeApi.chooseArm(projectId, arm, by, supersede),
    onSuccess: commit,
  });

  const retryStage = useMutation({
    mutationFn: (stageId: CodeStageId) => codeApi.retryStage(projectId, stageId),
    onSuccess: commit,
  });

  const submitDecision = useMutation({
    mutationFn: (decision: CodeDecisionInput) => codeApi.submitDecision(projectId, decision),
    onSuccess: commit,
  });

  const continueRun = useMutation({
    mutationFn: (runId: string) => codeApi.continueRun(projectId, runId),
    onSuccess: commit,
  });

  return {
    generate,
    setStoryScope,
    planNextSprint,
    selectStack,
    chooseArm,
    retryStage,
    submitDecision,
    continueRun,
    /** Puts a snapshot the server answered with in place, as every mutation does. */
    commit,
  };
}

/**
 * The preview: a process, polled on its own cadence.
 *
 * Separate from the snapshot because it is not an artefact and does not move
 * with a run. Polled while it is coming up, because installing and building
 * takes tens of seconds and the reader is watching; polled slowly once it is
 * running, because that read is also what tells the server somebody is still
 * looking and stops the idle sweep reclaiming it.
 */
export function usePreview(projectId: string) {
  return useQuery({
    queryKey: codeKeys.preview(projectId),
    queryFn: () => codeApi.getPreview(projectId),
    enabled: Boolean(projectId),
    refetchInterval: (query) => (query.state.data?.status === "starting" ? 1500 : 30_000),
  });
}

export function usePreviewMutations(projectId: string) {
  const client = useQueryClient();
  const key = codeKeys.preview(projectId);

  const start = useMutation({
    mutationFn: () => codeApi.startPreview(projectId),
    onSuccess: (state) => client.setQueryData(key, state),
    // The preview panel shows why it could not start, under its button.
    meta: { reportsOwnErrors: true },
  });

  const stop = useMutation({
    mutationFn: () => codeApi.stopPreview(projectId),
    onSuccess: () => client.setQueryData(key, { status: "none" as const }),
  });

  return { start, stop };
}
