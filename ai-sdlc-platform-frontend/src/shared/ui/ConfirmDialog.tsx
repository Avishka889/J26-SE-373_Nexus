import { useRef } from "react";
import { useDialogFocus } from "@/shared/ui/useDialogFocus";
import { cn } from "@/shared/utils/cn";
import { surface } from "@/shared/ui/surface";

/**
 * A yes or no a reader has to answer before something irreversible happens.
 *
 * Built because deleting a project was one click on a trash icon that only
 * appeared on hover, with a toast afterwards saying it had already happened.
 * Artefacts cascade from projects, so that click destroyed every stored version
 * of every artefact for that project: in this repository those are the
 * evaluation record, not a cache.
 *
 * The destructive action is not the default focus. A reader who opens this by
 * accident and presses Enter should cancel, not confirm.
 */
export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  isDark,
  onConfirm,
  onCancel,
}: {
  title: string;
  /** What will happen, in the reader's terms. Name the thing, not the table. */
  body: string;
  confirmLabel: string;
  isDark: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  // Focus starts on Cancel, stays inside, and goes back to what opened it.
  const dialog = useRef<HTMLDivElement>(null);
  useDialogFocus(dialog, onCancel);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        aria-label="Cancel"
        onClick={onCancel}
      />
      <div
        ref={dialog}
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          "relative z-10 w-full max-w-[420px] overflow-hidden rounded-2xl shadow-2xl",
          surface.modal(isDark),
        )}
      >
        <div className="px-5 pb-4 pt-5">
          <h2 className="text-[15px] font-semibold text-[color:var(--tp-ink)]">{title}</h2>
          <p className="mt-1.5 text-[13px] text-[color:var(--tp-ink-2)]">{body}</p>
        </div>
        <div
          className={cn(
            "flex justify-end gap-2 border-t px-5 py-3",
            isDark ? "border-white/[0.06]" : "border-slate-100",
          )}
        >
          <button
            data-autofocus
            type="button"
            onClick={onCancel}
            className={cn(
              "rounded-xl px-3.5 py-2 text-[13px] font-medium transition-colors",
              isDark
                ? "text-slate-300 hover:bg-white/[0.06]"
                : "text-slate-600 hover:bg-slate-100",
            )}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-xl bg-red-600 px-3.5 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-red-500"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
