/**
 * The two ways the API contract is inferred, in a reader's words.
 *
 * "Rule arm" and "LLM arm" are the study's terms: a deterministic rule and a
 * model, run on the same input and compared. The pages said them as they are
 * said in the dissertation, which a developer reading a code review should not
 * have to translate.
 */
export const ARM_NAMES: Record<string, string> = {
  rule: "Rule-based",
  llm: "AI model",
  merged: "Merged",
};

/** "inferred by rule", for the summaries that say where the contract came from. */
export function inferredBy(arm: string): string {
  if (arm === "rule") return "inferred by rule";
  if (arm === "llm") return "inferred by the AI model";
  if (arm === "merged") return "merged from both methods";
  return `inferred by ${arm}`;
}
