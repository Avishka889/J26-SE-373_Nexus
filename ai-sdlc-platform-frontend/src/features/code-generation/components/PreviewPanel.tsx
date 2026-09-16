import { AlertTriangle, ExternalLink, Play, Square } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { Button } from "@/shared/ui/primitives";
import { Note, Panel } from "@/shared/ui/phase";
import { StageSection } from "@/shared/ui/stage";
import { usePreview, usePreviewMutations } from "../hooks/useCode";
import type { CodeSnapshot } from "../api/types";
import { Spinner } from "@/shared/ui/Spinner";

/**
 * The generated app, running.
 *
 * Not an embedded frame: the app is served from a different origin on a port
 * of its own, and putting it in an iframe would mean pretending it is part of
 * this page while its routing, its storage and its errors are not. A link that
 * opens it in its own tab is what it is.
 *
 * Everything here says plainly what is being run, because what is being run is
 * a language model's code on this machine. Nothing is started by arriving on
 * the page, the address is loopback so it is reachable from nowhere else, and
 * the panel says the data starts empty rather than leaving a reader to wonder
 * why the lists are.
 */
const DOT: Record<string, string> = {
  running: "bg-emerald-500",
  starting: "bg-amber-500",
  failed: "bg-red-500",
  stopped: "bg-[color:var(--tp-muted)]",
  none: "bg-[color:var(--tp-muted)]",
  unavailable: "bg-[color:var(--tp-muted)]",
};

export function PreviewPanel({
  projectId,
  snapshot,
  buildPassed,
}: {
  projectId: string;
  snapshot: CodeSnapshot;
  buildPassed: boolean;
}) {
  const query = usePreview(projectId);
  const { start, stop } = usePreviewMutations(projectId);
  const preview = query.data;
  const status = preview?.status ?? "none";
  const busy = start.isPending || stop.isPending || status === "starting";
  const stale =
    status === "running" &&
    preview?.codeVersion !== undefined &&
    preview.codeVersion !== snapshot.codeVersion;

  return (
    <StageSection id="build-preview">
      <Panel
        label="Preview"
        title="The generated app, running on this machine."
        icon={<span className={cn("block h-2.5 w-2.5 rounded-full", DOT[status])} />}
      >
        {status === "unavailable" ? (
          <Note>
            {preview?.reason ??
              "Previews run the generated app on the server, so they need the live backend."}
          </Note>
        ) : !buildPassed ? (
          <Note>
            This code version did not build, so there is nothing to preview. Read the build
            steps above, fix what they report, and generate again.
          </Note>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3">
              {status === "running" && preview?.url ? (
                <>
                  <a
                    href={preview.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-xl border border-blue-500/40 bg-blue-500/[0.07] px-3 py-2 text-[13px] font-medium text-blue-600 transition-colors hover:border-blue-500/70 dark:text-blue-300"
                  >
                    Open the app
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                  <span className="tp-mono text-[11.5px] text-[color:var(--tp-ink-2)]">
                    {preview.url}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    busy={stop.isPending}
                    onClick={() => stop.mutate()}
                  >
                    <Square className="h-3.5 w-3.5" />
                    Stop
                  </Button>
                </>
              ) : status === "starting" ? (
                <p className="tp-den flex items-center gap-2">
                  <Spinner size="xs" decorative />
                  Installing dependencies and building, which takes a minute the first time
                </p>
              ) : (
                <Button
                  variant="primary"
                  size="sm"
                  disabled={busy}
                  busy={start.isPending}
                  onClick={() => start.mutate()}
                >
                  <Play className="h-3.5 w-3.5" />
                  Run the app
                </Button>
              )}
            </div>

            {stale && (
              <Note className="mt-3">
                This preview is serving code version {preview?.codeVersion} and the project is
                now at {snapshot.codeVersion}. Run it again to serve the newer one.
              </Note>
            )}

            {(status === "failed" || status === "stopped") && preview?.error && (
              <div
                className={cn(
                  "mt-3 rounded-xl border px-3.5 py-3",
                  status === "failed"
                    ? "border-red-500/30 bg-red-500/5"
                    : "border-[color:var(--tp-line)]",
                )}
              >
                <p className="flex items-center gap-2 text-[13px] font-semibold text-[color:var(--tp-ink)]">
                  {status === "failed" && (
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-red-500" />
                  )}
                  {status === "failed" ? "It did not start" : "It was stopped"}
                </p>
                <Note className="mt-1">{preview.error}</Note>
              </div>
            )}

            {start.isError && (
              <Note className="mt-3">{(start.error as Error).message}</Note>
            )}

            <Note className="mt-3">
              One process serves both sides on <span className="tp-mono">127.0.0.1</span>, so it is
              reachable from this machine and nowhere else. It runs generated code with none of the
              platform's own environment, and stops on its own once nobody has looked at it for a
              while. The repositories are in memory, so the lists start empty and reset when it
              restarts.
            </Note>
          </>
        )}
      </Panel>
    </StageSection>
  );
}
