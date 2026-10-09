import type { AttachmentSlot } from "@/types/document";
import { surface } from "@/shared/ui/surface";

/**
 * Chip border, background and text per state, literal classes so Tailwind can see
 * them. A function of `isDark` rather than a static map because the failed state
 * borrows `surface.danger`, which is itself keyed on the theme.
 */
export function chipTone(isDark: boolean) {
  return {
    ready: "border-[color:var(--tp-line)]",
    reading: "border-[color:var(--tp-line)] opacity-70",
    failed: surface.danger(isDark),
  } as const;
}

const NUMBER = new Intl.NumberFormat();

/**
 * What the chip says it read.
 *
 * Every way a document can be read incompletely is named here rather than
 * hidden. Silently keeping the first part of a long document, or silently
 * skipping the scanned pages of a mixed one, is the same class of bug as
 * silently ignoring the file: the reader believes the design was generated from
 * something it was not.
 */
export function describe(slot: Extract<AttachmentSlot, { state: "ready" }>): string {
  const { document: doc } = slot;
  const parts: string[] = [];
  if (doc.pages !== null) parts.push(`${doc.pages} ${doc.pages === 1 ? "page" : "pages"}`);
  parts.push(
    doc.truncated
      ? `first ${NUMBER.format(doc.chars)} of ${NUMBER.format(doc.charsAvailable)} characters read`
      : `${NUMBER.format(doc.words)} ${doc.words === 1 ? "word" : "words"}`,
  );
  if (doc.pagesWithoutText) {
    parts.push(`${doc.pagesWithoutText} with no readable text`);
  }
  return parts.join(" · ");
}
