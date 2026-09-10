import { useEffect, useRef, type ReactNode } from "react";
import { useDialogFocus } from "@/shared/ui/useDialogFocus";
import { X } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { surface } from "@/shared/ui/surface";

/**
 * The architecture graph, given the whole window.
 *
 * A modal for the same reasons the diagram one is: the wireframe player already
 * set that gesture here, the Fullscreen API needs its own user gesture and
 * differs by browser, and it takes away the chrome a reader uses to get back.
 *
 * No zoom controls of its own. React Flow already draws them, along with fit and
 * a minimap, so a second set would be two controls disagreeing about the same
 * canvas. The canvas is handed in whole rather than rebuilt, which is also what
 * keeps the filters and the selection the reader already set.
 */
export function GraphCanvasModal({
  title,
  isDark,
  onClose,
  children,
}: {
  title: string;
  isDark: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);

  const dialog = useRef<HTMLDivElement>(null);
  useDialogFocus(dialog, onClose);
  // Declared after the hook, so the opener it records is the page's, not this.
  useEffect(() => closeRef.current?.focus(), []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        aria-label="Close the graph"
        onClick={onClose}
      />
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          // A fixed frame, like the diagram window: a canvas that resizes to
          // its contents moves the graph under the reader between openings.
          "relative z-10 flex h-[88vh] w-full max-w-[1280px] flex-col overflow-hidden rounded-2xl shadow-2xl",
          surface.modal(isDark),
        )}
      >
        <div
          className={cn(
            "flex items-center justify-between gap-3 border-b px-5 py-3.5",
            isDark ? "border-white/[0.06]" : "border-slate-100",
          )}
        >
          <h2 className="truncate text-[15px] font-semibold text-[color:var(--tp-ink)]">{title}</h2>
          <button
            ref={closeRef}
            type="button"
            aria-label="Close"
            title="Close"
            onClick={onClose}
            className={cn(
              "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border transition-colors",
              isDark
                ? "border-white/10 text-slate-300 hover:bg-white/[0.06]"
                : "border-slate-200 text-slate-600 hover:bg-slate-100",
            )}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className={cn("flex-1", isDark ? "bg-[#0a0e17]" : "bg-slate-50")}>{children}</div>
      </div>
    </div>
  );
}
