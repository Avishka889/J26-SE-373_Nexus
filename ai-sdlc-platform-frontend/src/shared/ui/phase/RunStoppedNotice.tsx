import { useState } from "react";
import { AlertTriangle, Play, RotateCcw } from "lucide-react";
import { Button } from "@/shared/ui/primitives";
import { formatWhen } from "@/shared/utils/time";

/**
 * A run that stopped before it finished, said where the reader looks first.
 *
 * Without it the page showed the stages the run never reached as waiting for
 * the stage before them, and a review that never came; the reason was only in
 * Activity, and nothing offered a way on.
 *
 * Continuing comes first when the page offers it: it goes on from the stage
 * that stopped the run, where starting over generates every stage again and
 * pays again for each one that had finished.
 */
export function RunStoppedNotice({
  error,
  startedAt,
  onContinue,
  stoppedAtLabel,
  onStartOver,
  startOverHint,
  busy: pending,
}: {
  /** The server's reason, in plain words. */
  error: string;
  startedAt: string;
  /** May resolve when the server has answered, which keeps the buttons busy. */
  onContinue?: () => void | Promise<unknown>;
  /** The stage the run stopped at, in the phase's own words. */
  stoppedAtLabel?: string;
  onStartOver: () => void | Promise<unknown>;
  /** What starting over redoes, in the phase's own words. */
  startOverHint: string;
  /** The page's own request is in flight, for a handler that does not resolve with it. */
  busy?: boolean;
}) {
  const [waiting, setWaiting] = useState<"continue" | "start-over" | null>(null);
  const busy = waiting !== null || Boolean(pending);
  const act = async (which: "continue" | "start-over", handler: () => void | Promise<unknown>) => {
    if (busy) return;
    setWaiting(which);
    try {
      await handler();
    } catch {
      // Reported by the page; the buttons only have to be offered again.
    } finally {
      setWaiting(null);
    }
  };

  return (
    <section
      role="alert"
      className="rounded-xl border border-red-500/30 bg-red-500/5 px-3.5 py-3 text-[13px] text-[color:var(--tp-ink)]"
    >
      <div className="flex items-start gap-2.5">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold">The last run stopped before it finished</p>
          <p className="mt-1 break-words text-[color:var(--tp-ink-2)]">
            {sentence(error)} It started at {formatWhen(startedAt)}. The stages it did not reach are marked below.
          </p>
          <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
            {onContinue && (
              <Button
                variant="primary"
                size="sm"
                busy={waiting === "continue"}
                disabled={busy}
                onClick={() => void act("continue", onContinue)}
              >
                <Play className="h-3.5 w-3.5" />
                {stoppedAtLabel ? `Continue from ${stoppedAtLabel}` : "Continue from where it stopped"}
              </Button>
            )}
            <Button
              variant={onContinue ? "outline" : "primary"}
              size="sm"
              busy={waiting === "start-over" || (Boolean(pending) && waiting === null)}
              disabled={busy}
              onClick={() => void act("start-over", onStartOver)}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Start over
            </Button>
          </div>
          <p className="tp-den mt-1.5">
            {onContinue
              ? `Continuing generates ${stoppedAtLabel ?? "the stage that stopped it"} and the stages after it, and nothing that finished. ${startOverHint}`
              : startOverHint}
          </p>
        </div>
      </div>
    </section>
  );
}

function sentence(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return "No reason was recorded.";
  const capital = trimmed[0].toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(capital) ? capital : `${capital}.`;
}
