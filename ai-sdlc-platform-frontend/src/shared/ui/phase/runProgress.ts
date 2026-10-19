/** The phase's newest full run, as every snapshot carries it. */
type RunFacts = { state: string } | null | undefined;

/**
 * Whether the phase's run is still going: queued, or running.
 *
 * Not the same as a stage generating. A run marks every stage it will produce
 * as generating when it starts, but a review produces nothing of its own and
 * stays pending until the run opens it. So between the last stage finishing
 * and the review opening, no stage is generating while the run still is, and a
 * page that asked again only while a stage generated stopped asking at exactly
 * that moment: the review appeared only when something else made it read.
 */
export function runIsWorking(run: RunFacts): boolean {
  return run?.state === "queued" || run?.state === "running";
}

/**
 * The stage a working run opens next, when no stage is generating.
 *
 * That is the review between the last stage finishing and the review opening,
 * or the first stage of a run that is queued and has not marked any. Null
 * while a stage is generating, since that stage is the one being worked on and
 * the pages say so, and null once the run waits at its gate or has ended.
 */
export function stageOpeningNext<Id extends string>(
  order: readonly Id[],
  stages: Partial<Record<Id, { status: string }>>,
  run: RunFacts,
): Id | null {
  if (!runIsWorking(run)) return null;
  if (order.some((one) => stages[one]?.status === "generating")) return null;
  return order.find((one) => stages[one]?.status === "pending") ?? null;
}
