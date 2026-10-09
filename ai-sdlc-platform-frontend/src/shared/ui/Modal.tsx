import { useRef, type ReactNode } from "react";
import { useDialogFocus } from "@/shared/ui/useDialogFocus";
import { X } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { useIsDark } from "@/shared/theme";

/**
 * A fixed frame with a scrim, a title bar and an escape hatch.
 *
 * Extracted from the UML diagram modal when the code viewer needed the same
 * thing: the scrim, the escape key, the labelled dialog role and the close
 * control are the parts nobody should write twice, and the part that differs
 * between a diagram and a file is only what goes inside.
 *
 * A modal rather than the Fullscreen API, for the reason the diagram viewer
 * chose one: fullscreen needs a user gesture, behaves differently per browser,
 * and takes away the chrome a reader uses to get back.
 */
export function Modal({
  title,
  subtitle,
  onClose,
  actions,
  children,
  className,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  /** Controls in the title bar, beside the close button. */
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const isDark = useIsDark();

  const dialog = useRef<HTMLDivElement>(null);
  useDialogFocus(dialog, onClose);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        aria-label={`Close ${title}`}
        onClick={onClose}
      />
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          // A fixed frame rather than one that fits its content: a viewer whose
          // size changes with what it is showing makes every next thing land
          // somewhere different.
          "relative flex h-[min(86vh,900px)] w-[min(96vw,1100px)] flex-col overflow-hidden rounded-2xl border shadow-2xl",
          isDark ? "border-white/10 bg-[#0b1626]" : "border-slate-200 bg-white",
          className,
        )}
      >
        <div
          className={cn(
            "flex shrink-0 items-center gap-3 border-b px-4 py-3",
            isDark ? "border-white/10" : "border-slate-200",
          )}
        >
          <div className="min-w-0 flex-1">
            <p
              className={cn(
                "truncate text-[13.5px] font-semibold",
                isDark ? "text-slate-100" : "text-slate-800",
              )}
            >
              {title}
            </p>
            {subtitle && (
              <p
                className={cn(
                  "tp-mono truncate text-[11px]",
                  isDark ? "text-slate-400" : "text-slate-500",
                )}
              >
                {subtitle}
              </p>
            )}
          </div>
          {actions}
          <button
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
        <div className="min-h-0 flex-1 overflow-auto">{children}</div>
      </div>
    </div>
  );
}
