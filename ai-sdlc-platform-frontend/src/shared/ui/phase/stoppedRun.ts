type Run = { state: string; error?: string | null; startedAt: string };

/**
 * The phase's newest full run when it stopped before finishing, and nothing
 * is running now. One rule for every phase: once a new run is generating,
 * that run is the way on and the notice about the old one goes.
 */
export function stoppedRun<T extends Run>(
  run: T | null | undefined,
  generating: boolean,
): (T & { error: string }) | null {
  if (!run || run.state !== "failed" || generating) return null;
  return { ...run, error: run.error ?? "" };
}
