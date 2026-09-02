import { useCallback, useMemo, useState } from "react";
import type { Attachment, AttachmentSlot } from "@/types/document";
import { extractDocument } from "./api";

/**
 * The attachments one composer is holding.
 *
 * Memory only, on purpose: nothing is stored server side, and the extracted text
 * has one home, which is the project's requirement text once the composer is
 * submitted.
 */
export function useAttachments(): {
  slots: AttachmentSlot[];
  documents: Attachment[];
  /** How many picked files have no text yet. Zero before a composer may submit. */
  readingCount: number;
  add(files: FileList | File[]): void;
  remove(id: string): void;
} {
  const [slots, setSlots] = useState<AttachmentSlot[]>([]);

  const add = useCallback((files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      const id = crypto.randomUUID();
      setSlots((prev) => [...prev, { state: "reading", id, name: file.name }]);

      extractDocument(file)
        .then((document) =>
          setSlots((prev) =>
            prev.map((slot) =>
              slot.id === id ? { state: "ready", id, document: { ...document, id } } : slot,
            ),
          ),
        )
        .catch((err: unknown) =>
          setSlots((prev) =>
            prev.map((slot) =>
              slot.id === id
                ? {
                    state: "failed",
                    id,
                    name: file.name,
                    reason: err instanceof Error ? err.message : "That file could not be read.",
                  }
                : slot,
            ),
          ),
        );
    }
  }, []);

  const remove = useCallback((id: string) => {
    setSlots((prev) => prev.filter((slot) => slot.id !== id));
  }, []);

  const documents = useMemo(
    () =>
      slots.flatMap((slot) => (slot.state === "ready" ? [slot.document] : [])),
    [slots],
  );

  // The other half of `documents`, and the half a composer used to have no way
  // to see. A file being read is in `slots` and not in `documents`, so a submit
  // that guarded only on the composed text sent the typed sentence alone,
  // started the run, and unmounted the composer with the read still in flight:
  // the attached document was named nowhere and dropped. Counted rather than a
  // boolean so a control can say how many files it is waiting for.
  const readingCount = useMemo(
    () => slots.filter((slot) => slot.state === "reading").length,
    [slots],
  );

  return { slots, documents, readingCount, add, remove };
}
