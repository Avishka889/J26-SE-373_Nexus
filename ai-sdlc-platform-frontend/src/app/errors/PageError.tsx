import { AlertTriangle } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/shared/ui/primitives";
import { Note, Panel } from "@/shared/ui/phase";
import { isStaleChunk } from "./staleChunks";

const STALE_TITLE = "A newer version of the app is available";
const STALE_TEXT =
  "Part of this page changed since it was opened. Reloading fetches the current version; nothing that was saved is lost.";

/** A page that failed to render, in its place inside the shell, which keeps working. */
export function PageError({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const stale = isStaleChunk(error);
  return (
    <div role="alert" className="tp w-full p-4 sm:p-6 md:p-8">
      <Panel
        icon={<AlertTriangle className="h-4 w-4" />}
        label={stale ? STALE_TITLE : "This page hit a problem"}
      >
        <Note>
          {stale
            ? STALE_TEXT
            : "Something on this page failed to display, and nothing was changed by it. Try again, or go back to your projects."}
        </Note>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {stale ? (
            <Button variant="primary" size="sm" onClick={() => window.location.reload()}>
              Reload
            </Button>
          ) : (
            <Button variant="primary" size="sm" onClick={onRetry}>
              Try again
            </Button>
          )}
          <Link
            to="/projects"
            className="inline-flex items-center rounded-lg border border-[color:var(--tp-line-strong)] px-3 py-1.5 text-[13px] font-medium text-[color:var(--tp-ink)] transition-colors hover:bg-[color:var(--tp-line)]"
          >
            Back to projects
          </Link>
        </div>
      </Panel>
    </div>
  );
}

/**
 * The last resort, when the app itself failed to render.
 *
 * Outside the router and the theme, both of which may be what failed, so it is
 * plain elements coloured from the tokens on `:root`, like the boot screen.
 */
export function AppError({ error }: { error: Error }) {
  const stale = isStaleChunk(error);
  return (
    <div className="flex min-h-screen items-center justify-center bg-[color:var(--tp-surface)] p-6">
      <div role="alert" className="max-w-md text-center">
        <p className="text-[16px] font-semibold text-[color:var(--tp-ink)]">
          {stale ? STALE_TITLE : "The app hit a problem"}
        </p>
        <p className="mt-2 text-[13px] leading-relaxed text-[color:var(--tp-ink-2)]">
          {stale
            ? STALE_TEXT
            : "It could not display this screen. Reloading usually clears it; nothing that was saved is lost."}
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-blue-500"
        >
          Reload
        </button>
      </div>
    </div>
  );
}
