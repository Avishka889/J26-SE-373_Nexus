import { CODE_STAGE_IDS } from "@/types/project";
import type { CodeSnapshot } from "../api/types";

/**
 * How far this phase has got, and what to call it.
 *
 * The design phase's rule, applied to the code axis: generating every artefact
 * is not the same as being finished, so a phase whose review is still pending
 * reads "Ready for review" rather than a number that would claim a decision
 * nobody made. The bar can sit full, because generation genuinely is complete.
 */
export function computeCodeProgress(snapshot: CodeSnapshot): {
  percent: number;
  valueLabel: string;
} {
  const stages = CODE_STAGE_IDS.map((id) => snapshot.stages[id]);
  const complete = stages.filter((s) => s.status === "complete").length;
  const percent = Math.round((complete / stages.length) * 100);
  const decision = snapshot.gate.decision;

  if (decision?.kind === "approved") return { percent: 100, valueLabel: "Approved" };
  if (decision?.kind === "changes") return { percent, valueLabel: "Changes requested" };
  if (stages.some((s) => s.status === "failed")) return { percent, valueLabel: "Needs attention" };
  if (stages.some((s) => s.status === "generating")) return { percent, valueLabel: "Generating" };
  if (snapshot.codeVersion === 0) return { percent: 0, valueLabel: "Not started" };
  if (complete === stages.length) return { percent: 100, valueLabel: "Ready for review" };
  return { percent, valueLabel: `${percent}%` };
}
