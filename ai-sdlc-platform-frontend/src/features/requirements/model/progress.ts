import { DESIGN_STAGE_IDS } from "@/types/project";
import type { DesignSnapshot } from "../api/types";

/**
 * How far this phase has got, and what to call it.
 *
 * Generating every artifact is not the same as being finished. A phase whose
 * gate is still pending is ready for review, and saying "100 percent" there
 * would claim a decision nobody made. The bar can sit full, because generation
 * genuinely is complete; the label is what carries the truth.
 */
export function computeDesignProgress(snapshot: DesignSnapshot): {
  percent: number;
  valueLabel: string;
} {
  const stages = DESIGN_STAGE_IDS.map((id) => snapshot.stages[id]);
  const complete = stages.filter((s) => s.status === "complete").length;
  const percent = Math.round((complete / stages.length) * 100);
  const decision = snapshot.gate.decision;

  if (decision?.kind === "approved") return { percent: 100, valueLabel: "Approved" };
  if (decision?.kind === "changes") return { percent, valueLabel: "Changes requested" };
  if (stages.some((s) => s.status === "failed")) return { percent, valueLabel: "Needs attention" };
  // Named rather than numbered while work is in flight: a new project reading
  // "13%" beside a spinner says less than one word that matches the pill, the
  // chevron and the stage panel. The bar still carries the fraction.
  if (stages.some((s) => s.status === "generating")) return { percent, valueLabel: "Generating" };
  if (complete === stages.length) return { percent: 100, valueLabel: "Ready for review" };
  return { percent, valueLabel: `${percent}%` };
}
