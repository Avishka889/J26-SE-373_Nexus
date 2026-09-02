const KEY = "sdlc-stale-chunk-reload";
const WINDOW_MS = 60_000;

/**
 * Reload once when a page's code chunk is gone.
 *
 * Pages are split into chunks, so a tab opened before a redeploy names chunks
 * the server no longer has, and opening another page fails. Vite says so with
 * `vite:preloadError`, and one reload fetches the new page. A second failure
 * within a minute is a different problem: it is left to the error boundary to
 * say so, rather than reloading in a loop. Without a place to remember the
 * reload in, it does not reload at all, for the same reason.
 */
export function installStaleChunkReload(target: Window = window): () => void {
  const onPreloadError = (event: Event) => {
    try {
      const last = Number(target.sessionStorage.getItem(KEY) ?? 0);
      if (Date.now() - last < WINDOW_MS) return;
      target.sessionStorage.setItem(KEY, String(Date.now()));
    } catch {
      return;
    }
    event.preventDefault();
    target.location.reload();
  };
  target.addEventListener("vite:preloadError", onPreloadError);
  return () => target.removeEventListener("vite:preloadError", onPreloadError);
}

/**
 * Whether a render failed because a code chunk could not be fetched.
 *
 * Pages are split into chunks, and a tab opened before a redeploy names chunks
 * the server no longer has. Trying again cannot help that; reloading does.
 * Each browser words the failure differently.
 */
export function isStaleChunk(error: unknown): boolean {
  const text = error instanceof Error ? `${error.name} ${error.message}` : String(error);
  return /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|ChunkLoadError/i.test(
    text,
  );
}
