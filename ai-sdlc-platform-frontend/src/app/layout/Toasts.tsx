import { CheckCircle2, AlertTriangle, Info, XCircle, X } from "lucide-react";
import { useUiStore, type Toast } from "@/store/ui";
import { cn } from "@/shared/utils/cn";

/**
 * The notices raised across the app, read out as they arrive.
 *
 * Two live regions sit in the page from the start, since a screen reader only
 * hears a region it was already listening to: errors go to the assertive one,
 * which interrupts, and everything else to the polite one. Neither is atomic,
 * so a new notice is read without the ones already showing. Errors stay until
 * dismissed (the store's rule), and the dismiss button says what it does.
 *
 * At the top, below the top bar: an error that stays would otherwise sit over
 * the bottom of the page, where every phase keeps its decision bar, and cover
 * the very button the reader needs after reading it.
 */
export function Toasts() {
  const toasts = useUiStore((s) => s.toasts);
  const removeToast = useUiStore((s) => s.removeToast);
  const theme = useUiStore((s) => s.theme);
  const isDark = theme === "dark";

  const errors = toasts.filter((toast) => toast.type === "error");
  const others = toasts.filter((toast) => toast.type !== "error");

  const card = (toast: Toast) => {
    const Icon =
      toast.type === "success"
        ? CheckCircle2
        : toast.type === "error"
          ? XCircle
          : toast.type === "warning"
            ? AlertTriangle
            : Info;
    const color =
      toast.type === "success"
        ? "text-emerald-500"
        : toast.type === "error"
          ? "text-red-500"
          : toast.type === "warning"
            ? "text-amber-500"
            : "text-blue-500";
    return (
      <div
        key={toast.id}
        className={cn(
          "flex w-full items-start gap-3 rounded-2xl border p-3 shadow-2xl sm:w-80",
          isDark ? "border-white/10 bg-[#0f1d32]" : "border-slate-200 bg-white",
        )}
      >
        <Icon aria-hidden="true" className={cn("mt-0.5 h-5 w-5 shrink-0", color)} />
        <div className="min-w-0 flex-1">
          <p className={cn("text-sm font-medium", isDark ? "text-white" : "text-slate-800")}>
            {toast.title}
          </p>
          {toast.message && (
            <p className={cn("break-words text-xs", isDark ? "text-slate-400" : "text-slate-500")}>
              {toast.message}
            </p>
          )}
        </div>
        <button
          type="button"
          aria-label="Dismiss"
          title="Dismiss"
          onClick={() => removeToast(toast.id)}
          className="rounded p-0.5"
        >
          <X aria-hidden="true" className={cn("h-3.5 w-3.5", isDark ? "text-slate-400" : "text-slate-500")} />
        </button>
      </div>
    );
  };

  return (
    <section
      aria-label="Notifications"
      className="fixed left-4 right-4 top-16 z-[90] flex flex-col sm:left-auto sm:right-4 sm:w-96"
    >
      <div role="status" aria-live="polite" aria-atomic="false" className="flex flex-col gap-2">
        {others.map(card)}
      </div>
      <div
        role="alert"
        aria-live="assertive"
        aria-atomic="false"
        className={cn("flex flex-col gap-2", others.length > 0 && errors.length > 0 && "mt-2")}
      >
        {errors.map(card)}
      </div>
    </section>
  );
}
