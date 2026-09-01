import { compareServerTimes } from "@/shared/utils/time";
import type { StageChrome } from "./types";

type Generated = { status: string; generatedAt?: string | null };

/**
 * The stages this one reads that were generated again after it was computed.
 *
 * A stage retried alone regenerates that stage and nothing after it: a
 * changelog retried while the review waited left the risk levels computed from
 * the vote it replaced, and nothing said so. Read from the stages' own times
 * rather than a stored flag, so the answer cannot go stale itself. Compared as
 * moments, not text: a time stored before the wire carried zones has another
 * shape, and as text it sorts before every newer one.
 */
export function computedBefore<Id extends string>(
  reads: Partial<Record<Id, readonly Id[]>> | undefined,
  stageId: Id,
  stages: Partial<Record<Id, Generated>>,
): Id[] {
  const own = stages[stageId];
  if (own?.status !== "complete" || !own.generatedAt) return [];
  const computed = own.generatedAt;
  return (reads?.[stageId] ?? []).filter((read) => {
    const other = stages[read];
    return (
      other?.status === "complete" &&
      !!other.generatedAt &&
      compareServerTimes(other.generatedAt, computed) > 0
    );
  });
}

/** The same, in the phase's own words, for the stage shell to say. */
export function computedBeforeIn<Id extends string>(
  chrome: StageChrome<Id>,
  stageId: Id,
  stages: Partial<Record<Id, Generated>>,
): string[] {
  return computedBefore(chrome.reads, stageId, stages).map((id) => chrome.meta[id].label);
}
