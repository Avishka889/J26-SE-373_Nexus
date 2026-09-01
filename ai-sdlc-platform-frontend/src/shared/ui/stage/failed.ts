import type { StageChrome } from "./types";

/** The stages that failed, in the phase's own words and order. */
export function failedStagesIn<Id extends string>(
  chrome: StageChrome<Id>,
  stages: Partial<Record<Id, { status: string }>>,
): string[] {
  return chrome.ids.filter((id) => stages[id]?.status === "failed").map((id) => chrome.meta[id].label);
}

/** "Domain Model failed", or "2 stages failed: Domain Model, UML Diagrams"; null for none. */
export function failedStagesConcern(labels: string[]): string | null {
  if (labels.length === 0) return null;
  return labels.length === 1
    ? `${labels[0]} failed`
    : `${labels.length} stages failed: ${labels.join(", ")}`;
}
