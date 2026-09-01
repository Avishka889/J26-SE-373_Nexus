import { useCallback, useEffect, useRef, useState } from "react";
import { WifiOff } from "lucide-react";
import { Button } from "@/shared/ui/primitives";
import { Note, Panel } from "@/shared/ui/phase";

/**
 * Something the page needs could not be read from the server.
 *
 * It says so in place of the content, offers a retry, and keeps trying by
 * itself while it is shown, so a server that comes back is noticed without the
 * reader having to. The background tries are quiet: the panel stays until one
 * succeeds and whatever it guards replaces it.
 */
export function ServerUnavailable({
  title = "This could not be loaded",
  message,
  onRetry,
  retryEveryMs = 10_000,
}: {
  title?: string;
  /** The failure as a sentence, usually the request's own message. */
  message: string;
  onRetry: () => Promise<unknown>;
  retryEveryMs?: number;
}) {
  const [retrying, setRetrying] = useState(false);

  const retry = useCallback(async () => {
    setRetrying(true);
    try {
      await onRetry();
    } catch {
      // Still unavailable: the panel stays, with the newest reason.
    } finally {
      setRetrying(false);
    }
  }, [onRetry]);

  // The newest callback without restarting the interval, which a caller
  // passing a new function on every render would otherwise do forever.
  const latest = useRef(onRetry);
  useEffect(() => {
    latest.current = onRetry;
  }, [onRetry]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      void latest.current().catch(() => undefined);
    }, retryEveryMs);
    return () => window.clearInterval(timer);
  }, [retryEveryMs]);

  return (
    <div role="alert" className="tp w-full">
      <Panel icon={<WifiOff className="h-4 w-4" />} label={title}>
        <Note>{message} This is tried again every few seconds.</Note>
        <Button variant="primary" size="sm" className="mt-3" busy={retrying} onClick={() => void retry()}>
          Retry
        </Button>
      </Panel>
    </div>
  );
}
