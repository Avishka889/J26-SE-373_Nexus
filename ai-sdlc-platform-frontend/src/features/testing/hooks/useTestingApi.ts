import { useQuery } from "@tanstack/react-query";
import { testingKeys } from "@/lib/query";
import { isLive } from "@/lib/env";
import {
  getTestingSnapshot,
  testingDemoApi,
  type TestingSnapshot,
} from "../fixtures/legacyDemo";

/**
 * Sync fixture accessor for the demo page.
 * Prefer `useTestingSnapshot` when talking to a real backend.
 */
export function useTestingFixtures(): TestingSnapshot {
  return getTestingSnapshot();
}

export function useTestingSnapshot(projectId: string | null | undefined) {
  const id = projectId ?? "";

  return useQuery({
    queryKey: testingKeys.snapshot(id),
    queryFn: () => testingDemoApi.getSnapshot(id),
    // The demo's, never the live page's: it shares the live page's cache keys.
    enabled: Boolean(projectId) && !isLive("testing"),
    // Fixture mode can resolve immediately via the sync accessor when preferred.
    initialData:
      !isLive("testing") && projectId ? getTestingSnapshot() : undefined,
    staleTime: !isLive("testing") ? Infinity : 30_000,
  });
}

export function useTestingRun(projectId: string | null | undefined) {
  const id = projectId ?? "";
  return useQuery({
    queryKey: testingKeys.run(id),
    queryFn: () => testingDemoApi.getRun(id),
    // The demo's, never the live page's: it shares the live page's cache keys.
    enabled: Boolean(projectId) && !isLive("testing"),
  });
}

export function useTestingFailures(projectId: string | null | undefined) {
  const id = projectId ?? "";
  return useQuery({
    queryKey: testingKeys.failures(id),
    queryFn: () => testingDemoApi.getFailures(id),
    // The demo's, never the live page's: it shares the live page's cache keys.
    enabled: Boolean(projectId) && !isLive("testing"),
  });
}

export function useTestingFindings(projectId: string | null | undefined) {
  const id = projectId ?? "";
  return useQuery({
    queryKey: testingKeys.findings(id),
    queryFn: () => testingDemoApi.getFindings(id),
    // The demo's, never the live page's: it shares the live page's cache keys.
    enabled: Boolean(projectId) && !isLive("testing"),
  });
}

export function useTestingQuality(projectId: string | null | undefined) {
  const id = projectId ?? "";
  return useQuery({
    queryKey: testingKeys.quality(id),
    queryFn: () => testingDemoApi.getQuality(id),
    // The demo's, never the live page's: it shares the live page's cache keys.
    enabled: Boolean(projectId) && !isLive("testing"),
  });
}

export function useTestingAudit(projectId: string | null | undefined) {
  const id = projectId ?? "";
  return useQuery({
    queryKey: testingKeys.audit(id),
    queryFn: () => testingDemoApi.getAudit(id),
    // The demo's, never the live page's: it shares the live page's cache keys.
    enabled: Boolean(projectId) && !isLive("testing"),
  });
}

export function useTestingTestFiles(projectId: string | null | undefined) {
  const id = projectId ?? "";
  return useQuery({
    queryKey: testingKeys.testFiles(id),
    queryFn: () => testingDemoApi.getTestFiles(id),
    // The demo's, never the live page's: it shares the live page's cache keys.
    enabled: Boolean(projectId) && !isLive("testing"),
  });
}

export { testingDemoApi };
