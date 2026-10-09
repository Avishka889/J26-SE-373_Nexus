import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ReconnectingNotice } from "./ReconnectingNotice";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

/**
 * The page keeps what it showed and says it may be out of date.
 */
describe("the reconnecting notice", () => {
  it("says contact was lost and when the page was last read", () => {
    const at = new Date(2026, 9, 3, 14, 32).getTime();
    render(<ReconnectingNotice since={at} onRetry={vi.fn()} />);

    const notice = screen.getByRole("status").textContent ?? "";
    expect(notice).toContain("Lost contact with the server");
    expect(notice).toContain(new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
  });

  it("retries on request, and by itself while it is shown", async () => {
    vi.useFakeTimers();
    const onRetry = vi.fn();
    const { unmount } = render(<ReconnectingNotice since={Date.now()} onRetry={onRetry} retryEveryMs={10_000} />);

    fireEvent.click(screen.getByRole("button", { name: "Retry now" }));
    expect(onRetry).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(onRetry).toHaveBeenCalledTimes(2);

    unmount();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(onRetry).toHaveBeenCalledTimes(2);
  });
});
