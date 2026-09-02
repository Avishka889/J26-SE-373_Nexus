import { describe, expect, it, vi } from "vitest";
import { installStaleChunkReload } from "./staleChunks";

function fakeWindow(storage: "works" | "refused" = "works") {
  const stored = new Map<string, string>();
  const target = Object.assign(new EventTarget(), {
    location: { reload: vi.fn() },
    sessionStorage: {
      getItem: (key: string) => {
        if (storage === "refused") throw new Error("storage refused");
        return stored.get(key) ?? null;
      },
      setItem: (key: string, value: string) => {
        if (storage === "refused") throw new Error("storage refused");
        stored.set(key, value);
      },
    },
  });
  return target as unknown as Window & { location: { reload: ReturnType<typeof vi.fn> } };
}

function preloadError() {
  return new Event("vite:preloadError", { cancelable: true });
}

/**
 * A redeploy under an open tab heals itself once.
 *
 * Code is split per page, and a tab opened before a redeploy names chunks the
 * server no longer has. Vite says so with `vite:preloadError`; one reload
 * fetches the new page. A second failure within a minute is something else,
 * and is left to the error boundary rather than reloading in a loop.
 */
describe("a page chunk that is gone", () => {
  it("reloads the page once, instead of failing the import", () => {
    const target = fakeWindow();
    installStaleChunkReload(target);
    const event = preloadError();

    target.dispatchEvent(event);

    expect(target.location.reload).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(true);
  });

  it("does not reload again within a minute, so it cannot loop", () => {
    const target = fakeWindow();
    installStaleChunkReload(target);
    target.dispatchEvent(preloadError());

    const again = preloadError();
    target.dispatchEvent(again);

    expect(target.location.reload).toHaveBeenCalledTimes(1);
    expect(again.defaultPrevented).toBe(false);
  });

  it("does not reload at all when it cannot remember having reloaded", () => {
    const target = fakeWindow("refused");
    installStaleChunkReload(target);

    target.dispatchEvent(preloadError());

    expect(target.location.reload).not.toHaveBeenCalled();
  });

  it("stops listening when uninstalled", () => {
    const target = fakeWindow();
    const uninstall = installStaleChunkReload(target);
    uninstall();

    target.dispatchEvent(preloadError());

    expect(target.location.reload).not.toHaveBeenCalled();
  });
});
