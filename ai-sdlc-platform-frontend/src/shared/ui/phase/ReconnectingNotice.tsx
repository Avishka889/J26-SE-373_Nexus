import { useEffect, useRef } from "react";
import { WifiOff } from "lucide-react";

/**
 * A later read failed, and the page still shows what it read before.
 *
 * The content stays, and so does anything being typed in it, with a line
 * saying it may be out of date, a retry, and a quiet retry of its own while it
 * is shown, so contact coming back clears it without a click.
 */
export function ReconnectingNotice({
  since,
  onRetry,
  retryEveryMs = 10_000,
}: {
  /** When the shown data was read, in milliseconds since the epoch. */
  since: number;
  onRetry: () => void;
  retryEveryMs?: number;
}) {
  // The newest callback without restarting the interval: pages pass a new
  // function on every render, and a poll re-renders often enough that an
  // interval keyed on it would never fire.
  const latest = useRef(onRetry);
  useEffect(() => {
    latest.current = onRetry;
  }, [onRetry]);
  useEffect(() => {
    const timer = window.setInterval(() => latest.current(), retryEveryMs);
    return () => window.clearInterval(timer);
  }, [retryEveryMs]);

  const at = since
    ? new Date(since).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : null;
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-amber-500/40 bg-amber-500/[0.08] px-3.5 py-2.5 text-[13px] text-[color:var(--tp-ink)]"
    >
      <WifiOff className="h-4 w-4 shrink-0 text-amber-700 dark:text-amber-400" aria-hidden="true" />
      <span className="min-w-0 flex-1">
        Lost contact with the server.{at ? ` Showing what was read at ${at};` : ""} trying again.
      </span>
      <button
        type="button"
        onClick={onRetry}
        className="text-[13px] font-medium text-blue-700 hover:underline dark:text-blue-300"
      >
        Retry now
      </button>
    </div>
  );
}
