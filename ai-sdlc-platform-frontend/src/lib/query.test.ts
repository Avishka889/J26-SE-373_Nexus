import { describe, expect, it, vi } from "vitest";
import { MutationObserver, QueryObserver, focusManager } from "@tanstack/react-query";
import { createQueryClient } from "./query";

/**
 * No mutation fails silently.
 *
 * Most mutations only said what to do on success, and nothing handled the
 * rest: Approve, Send, Answer, Save and Try again stopped spinning and nothing
 * happened. The cache reports every failure once, unless the mutation says it
 * shows its own.
 */
describe("a failed mutation", () => {
  it("is reported once, through the handler", async () => {
    const onMutationError = vi.fn();
    const client = createQueryClient({ onMutationError });
    const refusal = new Error("There is no code decision waiting on this project");

    await new MutationObserver(client, { mutationFn: () => Promise.reject(refusal) })
      .mutate()
      .catch(() => undefined);

    expect(onMutationError).toHaveBeenCalledTimes(1);
    expect(onMutationError).toHaveBeenCalledWith(refusal);
  });

  it("is left to a mutation that reports its own", async () => {
    const onMutationError = vi.fn();
    const client = createQueryClient({ onMutationError });

    await new MutationObserver(client, {
      mutationFn: () => Promise.reject(new Error("Nothing to generate from")),
      meta: { reportsOwnErrors: true },
    })
      .mutate()
      .catch(() => undefined);

    expect(onMutationError).not.toHaveBeenCalled();
  });
});

/**
 * A tab left open offered a decision made elsewhere since: nothing read the
 * phase again when the reader came back to it.
 */
describe("coming back to the page", () => {
  it("reads again what has gone stale", async () => {
    const client = createQueryClient();
    // As the provider does: an unmounted client hears nothing of focus.
    client.mount();
    let reads = 0;
    const key = ["testing", "p1", "snapshot"];
    client.setQueryData(key, "the review waits", { updatedAt: Date.now() - 60_000 });
    const observer = new QueryObserver(client, {
      queryKey: key,
      queryFn: async () => {
        reads += 1;
        return "decided elsewhere";
      },
      refetchOnMount: false,
    });
    const unsubscribe = observer.subscribe(() => undefined);

    focusManager.setFocused(false);
    focusManager.setFocused(true);
    await vi.waitFor(() => expect(reads).toBe(1));

    unsubscribe();
    client.unmount();
    focusManager.setFocused(undefined);
  });
});
