import type { DecisionChainStep, Severity } from "../fixtures/types";

/** The severities, most serious first: the order the findings' tiles read in. */
export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low"];

/**
 * What happens to a repair or a fix once a person decides it, as the platform
 * carries it out.
 *
 * A live page read these from the demo's snapshot, whose story has approved
 * changes landing on a branch and the suite rerunning by itself. Here an
 * applied fix makes a new code version, and that version's tests are run and
 * reviewed again before Deployment will start; the demo keeps its own words.
 */
export const DECISION_CHAIN: DecisionChainStep[] = [
  {
    id: "propose",
    label: "Testing proposes",
    detail:
      "Repairs to tests and fixes to code arrive with their evidence attached.",
  },
  {
    id: "approve",
    label: "You decide",
    detail:
      "One decision per item, in the failure inbox and the findings table.",
  },
  {
    id: "implement",
    label: "It is applied",
    detail:
      "An approved repair changes the test; an applied fix makes a new code version.",
  },
  {
    id: "reverify",
    label: "Tested again",
    detail:
      "A new code version's tests are run and reviewed before Deployment starts.",
  },
];

/**
 * What the coverage trend spans, said from the points it has. It read "Sprint 23
 * into Sprint 24" on every page, the demo's sprints, over a live run's one point.
 */
export function coverageTrendCaption(points: number): string {
  if (points === 0) return "Nothing measured yet";
  if (points === 1) return "One run measured so far";
  return `Across ${points} runs`;
}
