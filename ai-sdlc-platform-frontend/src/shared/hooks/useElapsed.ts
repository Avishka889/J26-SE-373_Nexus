import { useEffect, useState } from "react";
import { parseServerTime } from "@/shared/utils/time";

/**
 * "2m 14s" since a server time, kept current every second; null without one.
 *
 * Written for Testing's run button, and shared once every phase said how long
 * its working stage had been going.
 */
export function useElapsed(since: string | null | undefined): string | null {
  const started = parseServerTime(since)?.getTime() ?? null;
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (started === null) return;
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, [started]);
  if (started === null) return null;
  const seconds = Math.max(0, Math.floor((now - started) / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}
