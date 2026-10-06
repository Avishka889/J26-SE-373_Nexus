/**
 * What a closed list of verified release note claims says, in one line.
 *
 * Counted by kind, in the contract's order, which is the rule's: the kinds that
 * make an update High come first, so the evidence for a level is on the line a
 * reader sees without opening the list (NFR11 keeps level, evidence and files
 * together).
 */
const KIND_ORDER = [
  "breaking",
  "removal",
  "behavioural",
  "deprecation",
  "security",
  "fix",
  "feature",
  "other",
] as const;

export function claimsSummary(claims: { kind: string }[]): string {
  const counts = new Map<string, number>();
  for (const claim of claims) counts.set(claim.kind, (counts.get(claim.kind) ?? 0) + 1);
  const known: string[] = KIND_ORDER.filter((kind) => counts.has(kind));
  const rest = [...counts.keys()].filter((kind) => !known.includes(kind)).sort();
  const parts = [...known, ...rest].map((kind) => `${counts.get(kind)} ${kind}`);
  const noun = claims.length === 1 ? "verified claim" : "verified claims";
  return `${claims.length} ${noun}: ${parts.join(", ")}`;
}
