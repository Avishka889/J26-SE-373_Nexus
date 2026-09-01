/**
 * How a scroll the page makes itself moves: smoothly, unless the reader asked
 * their system for less motion.
 *
 * The stylesheet honoured the preference for its own animations and the page's
 * scripted scrolls did not: every anchor, chevron and file jump glided anyway.
 */
export function scrollMotion(): ScrollBehavior {
  return typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    ? "auto"
    : "smooth";
}
