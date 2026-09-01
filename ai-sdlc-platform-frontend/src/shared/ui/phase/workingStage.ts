import { parseServerTime } from "@/shared/utils/time";

/**
 * The stage a run is working on now, and since when.
 *
 * A run marks every stage it will produce as generating when it starts, so each
 * stage's own status put a spinner on all of them, and nothing said which one
 * was working or for how long. The stages run one after another, in the order
 * a phase lists them, so the one working is the first still generating, and it
 * started when the stage before it finished in this run, or with the run.
 *
 * `since` needs the full run in progress: during a stage retry the newest full
 * run is an older one, and its start is not this wait, so the stage is named
 * without a time.
 */
export function workingStage<Id extends string>(
  order: readonly Id[],
  stages: Partial<Record<Id, { status: string; generatedAt?: string | null }>>,
  runStartedAt: string | null | undefined,
): { id: Id; since: string | null } | null {
  const id = order.find((one) => stages[one]?.status === "generating");
  if (id === undefined) return null;
  const started = parseServerTime(runStartedAt);
  if (!started) return { id, since: null };
  let since = runStartedAt as string;
  let latest = started.getTime();
  for (const one of order) {
    const stage = stages[one];
    const finished = parseServerTime(stage?.generatedAt)?.getTime();
    if (stage?.status === "complete" && finished !== undefined && finished >= latest) {
      latest = finished;
      since = stage.generatedAt as string;
    }
  }
  return { id, since };
}
