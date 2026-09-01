import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ServerUnavailable } from "./ServerUnavailable";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

/**
 * A server that could not be reached is said so, and tried again.
 */
describe("the server unavailable panel", () => {
  it("says what failed and retries on request", async () => {
    const onRetry = vi.fn(() => Promise.reject(new Error("still down")));
    render(<ServerUnavailable message="Cannot reach the server." onRetry={onRetry} />);

    expect(screen.getByRole("alert").textContent).toContain("Cannot reach the server.");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    });

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("tries again by itself while it is shown", async () => {
    vi.useFakeTimers();
    const onRetry = vi.fn(() => Promise.reject(new Error("still down")));
    const { unmount } = render(
      <ServerUnavailable message="Cannot reach the server." onRetry={onRetry} retryEveryMs={10_000} />,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(onRetry).toHaveBeenCalledTimes(1);

    unmount();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
