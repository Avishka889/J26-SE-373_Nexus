import { useRef } from "react";
import { useDialogFocus } from "@/shared/ui/useDialogFocus";
import { X } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { surface } from "@/shared/ui/surface";

/**
 * The exact string that will be sent, not a preview of the file.
 *
 * This is the difference that matters. Showing the document would tell the reader
 * what they attached, which they already know. Showing the composed input tells
 * them what the model will actually read, which is the only thing they can
 * usefully check before a run starts.
 */
export function AttachmentPreview({
  composed,
  sources,
  hasTypedText,
  isDark,
  onClose,
}: {
  composed: string;
  /** Names in composition order, drawn as annotation outside the text. */
  sources: string[];
  /** Whether the textarea contributed anything, since `composed` alone cannot say. */
  hasTypedText: boolean;
  isDark: boolean;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  useDialogFocus(dialog, onClose);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/*
        Mouse-only dismiss surface: the header button below is the labelled way
        to close this dialog, and Escape also works. Hidden from the
        accessibility tree (and pulled out of tab order) rather than given its
        own name, so it never competes with the header button for anyone
        navigating by name or by keyboard; it stays clickable for the mouse.
      */}
      <button
        type="button"
        aria-hidden="true"
        tabIndex={-1}
        onClick={onClose}
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
      />
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-label="What will be analysed"
        className={cn(
          "relative flex max-h-[80vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl shadow-xl",
          surface.modal(isDark),
        )}
      >
        <div className={cn("flex items-start justify-between gap-4 border-b p-4", surface.border(isDark))}>
          <div className="min-w-0">
            <h2 className={cn("text-sm font-semibold", surface.heading(isDark))}>
              What will be analysed
            </h2>
            <p className={cn("mt-0.5 truncate text-xs", surface.muted(isDark))}>
              {sources.length > 0
                ? hasTypedText
                  ? `Typed text and ${sources.join(", ")}`
                  : sources.join(", ")
                : "Typed text"}
              {` · ${new Intl.NumberFormat().format(composed.length)} characters`}
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close preview" className="shrink-0 opacity-60 hover:opacity-100">
            <X className="h-4 w-4" />
          </button>
        </div>
        <pre
          className={cn(
            "tp-mono overflow-auto whitespace-pre-wrap break-words p-4 text-[12px] leading-relaxed",
            surface.body(isDark),
          )}
        >
          {composed}
        </pre>
      </div>
    </div>
  );
}
