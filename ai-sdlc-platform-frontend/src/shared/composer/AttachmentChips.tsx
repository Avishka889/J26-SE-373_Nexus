import { FileText, TriangleAlert, X } from "lucide-react";
import type { AttachmentSlot } from "@/types/document";
import { cn } from "@/shared/utils/cn";
import { surface } from "@/shared/ui/surface";
import { chipTone, describe } from "./describeAttachment";
import { Spinner } from "@/shared/ui/Spinner";

/**
 * One row of attachments above the composer controls.
 *
 * A failure keeps its place in the row instead of becoming a toast. The reason a
 * file was refused is the thing the reader has to act on, and a toast that says
 * "no readable text" and vanishes leaves them looking at an empty composer with
 * no idea what happened.
 */

export function AttachmentChips({
  slots,
  isDark,
  onRemove,
  onInspect,
}: {
  slots: AttachmentSlot[];
  isDark: boolean;
  onRemove: (id: string) => void;
  onInspect: () => void;
}) {
  if (slots.length === 0) return null;

  const tone = chipTone(isDark);

  return (
    <ul className="mb-3 flex flex-wrap gap-2">
      {slots.map((slot) => (
        <li
          key={slot.id}
          className={cn(
            "flex max-w-full items-center gap-2 rounded-xl border px-2.5 py-1.5 text-xs",
            tone[slot.state],
            slot.state !== "failed" && surface.body(isDark),
          )}
        >
          {slot.state === "reading" && <Spinner size="xs" decorative />}
          {slot.state === "failed" && <TriangleAlert className="h-3.5 w-3.5 shrink-0" />}
          {slot.state === "ready" && <FileText className="h-3.5 w-3.5 shrink-0" />}

          <span className="min-w-0">
            <span className="block truncate font-medium">
              {slot.state === "ready" ? slot.document.name : slot.name}
            </span>
            {slot.state === "ready" && (
              <button
                type="button"
                onClick={onInspect}
                className="block truncate text-[11px] underline decoration-dotted underline-offset-2 opacity-70 hover:opacity-100"
              >
                {describe(slot)}
              </button>
            )}
            {slot.state === "failed" && <span className="block text-[11px]">{slot.reason}</span>}
            {slot.state === "reading" && <span className="block text-[11px] opacity-70">Reading</span>}
          </span>

          <button
            type="button"
            aria-label={`Remove ${slot.state === "ready" ? slot.document.name : slot.name}`}
            onClick={() => onRemove(slot.id)}
            className="ml-auto shrink-0 opacity-60 hover:opacity-100"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </li>
      ))}
    </ul>
  );
}
