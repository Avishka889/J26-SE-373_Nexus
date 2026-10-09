/**
 * An attached document, after its text has been read.
 *
 * Lives in types/ rather than in the entity because `shared/composer` renders it
 * and the import direction is app -> features -> entities -> shared/lib/types:
 * shared may not reach back into entities.
 */

export type DocumentFormat = "pdf" | "docx" | "txt" | "md";

export interface Attachment {
  /** Stable for the session, so a chip can be removed without matching on name. */
  id: string;
  name: string;
  format: DocumentFormat;
  bytes: number;
  /** Pages for a PDF; null for formats with no fixed pagination. */
  pages: number | null;
  /**
   * Pages of a PDF that had no readable text; null for other formats.
   *
   * A document that is partly a scan is read partly, and the reader has to be
   * told which. Reading half a document and saying nothing is the same failure
   * as reading none of it and saying nothing, which is the bug this whole
   * feature exists to remove.
   */
  pagesWithoutText: number | null;
  words: number;
  chars: number;
  /** Length before the character limit, so the chip can say how much was skipped. */
  charsAvailable: number;
  truncated: boolean;
  text: string;
}

/**
 * What the composer shows for one file.
 *
 * A failure keeps its place in the row rather than becoming a toast. A toast
 * that says "no readable text" and then disappears leaves the reader looking at
 * a composer with nothing in it and no idea why.
 */
export type AttachmentSlot =
  | { state: "reading"; id: string; name: string }
  | { state: "ready"; id: string; document: Attachment }
  | { state: "failed"; id: string; name: string; reason: string };
