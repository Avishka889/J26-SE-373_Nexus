/** The phase's newest full run, as every snapshot carries it. */
type RunFacts = { state: string; version: number } | null | undefined;

/**
 * Whether the phase's review is open now, for the version on screen.
 *
 * The run says so: it waits at its gate exactly while the review is open. The
 * pages guessed from the review stage and the decision instead, and guessed
 * wrong both ways: after "Request changes" the bar came back at once while every
 * stage regenerated, and Approve was refused; after a failed or retired run, or
 * code that moved on, Testing offered a decision nobody could make. The demo's
 * fixtures carry no run, so they keep the rule they were written to.
 */
export function reviewIsOpen(run: RunFacts, version: number, withoutARun: () => boolean): boolean {
  if (!run) return withoutARun();
  return run.state === "awaiting_gate" && run.version === version;
}
