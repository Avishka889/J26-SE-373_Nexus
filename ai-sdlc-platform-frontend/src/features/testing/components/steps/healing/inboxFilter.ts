import type { ViewFailure } from "../../../model/view";

/**
 * Which failures each inbox tab shows.
 *
 * A type and a predicate, kept out of `HealingInbox.tsx` so that file exports
 * components only and can hot reload. The rule is data, not presentation: a
 * failure is "open" only on the current build, because a failure from an older
 * build has already been answered by a newer run.
 */

export type InboxFilter =
  | "attention"
  | "regression"
  | "unclassified"
  | "brittle"
  | "healed"
  | "awaiting"
  | "all";

export function matchesInboxFilter(failure: ViewFailure, filter: InboxFilter, build: number) {
  // A quarantined test is decided, so it waits on nobody; "all" still lists it.
  const open =
    failure.build === build && failure.state !== "healed" && failure.state !== "quarantined";
  switch (filter) {
    case "attention":
      return open;
    case "regression":
      return open && failure.triage === "regression";
    case "unclassified":
      return open && failure.triage === "unclassified";
    case "brittle":
      return open && failure.triage === "brittle";
    case "healed":
      return failure.state === "healed" || Boolean(failure.awaitingRerun);
    case "awaiting":
      return open && failure.state === "awaiting-approval";
    default:
      return true;
  }
}
