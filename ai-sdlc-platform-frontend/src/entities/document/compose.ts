import type { Attachment } from "@/types/document";

/**
 * The one string Component 1 reads.
 *
 * Called by the submit handler and by the preview panel, so what the reader sees
 * is literally what is sent. That is the whole reason it is a function rather
 * than two pieces of inline joining.
 *
 * Typed text first, then each document in the order it was attached, joined by a
 * blank line. Deliberately no "--- name.pdf ---" markers: they would land in the
 * string the rule layer measures for its extraction budget and that source_span
 * offsets index into, so provenance is recorded in the project's `files` list
 * instead of inside the text.
 */
export function composeRequirementText(typed: string, attachments: Attachment[]): string {
  return [typed.trim(), ...attachments.map((a) => a.text.trim())].filter(Boolean).join("\n\n");
}
