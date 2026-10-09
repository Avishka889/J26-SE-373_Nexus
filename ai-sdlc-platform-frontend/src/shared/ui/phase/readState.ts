/**
 * What a phase shows about its last read.
 *
 * TanStack Query marks a query as errored when a background refetch fails and
 * keeps the data it had, so "errored" alone cannot tell a page that never
 * loaded from one that lost contact a moment ago. Design and Code took any
 * error for a failed page and replaced the workspace, drafts and all; Testing
 * and Deployment showed nothing. One rule for all four:
 *
 * - `loading`: nothing has arrived yet;
 * - `failed`: the first read failed, so there is nothing to show but that;
 * - `stale`: a later read failed, so the last answer stays on screen, marked;
 * - `fresh`: the last read succeeded.
 */
export type ReadState = "loading" | "failed" | "stale" | "fresh";

export function readState(query: { isError: boolean; data: unknown }): ReadState {
  if (query.data === undefined) return query.isError ? "failed" : "loading";
  return query.isError ? "stale" : "fresh";
}
