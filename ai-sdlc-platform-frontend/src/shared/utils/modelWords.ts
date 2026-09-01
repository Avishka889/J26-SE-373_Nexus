/**
 * A run's and a stage's model settings, in the words the pages use.
 *
 * The same words the orchestrator writes into Activity (`THINKING_WORDS` in
 * its `wording.py`), so a reader meets one vocabulary in both places: a run
 * that turned thinking off says "thinking off" on its stage and in its log.
 */
const THINKING_WORDS: Record<string, string> = {
  disabled: "thinking off",
  default: "thinking left to the provider",
  // A phase's switch (`C1_THINKING` and the others), and the levels it records.
  off: "thinking off",
  low: "thinking on, low effort",
  high: "thinking on, high effort",
  max: "thinking on, max effort",
  enabled: "thinking on",
};

/** "disabled" as "thinking off"; a value with no words of its own still reads as words. */
export function thinkingWords(thinking: string): string {
  return THINKING_WORDS[thinking] ?? `thinking ${thinking}`;
}

const count = new Intl.NumberFormat("en");

/** "3,100" rather than "3100": a token count is read, not parsed. */
export function tokenCount(n: number): string {
  return count.format(n);
}
