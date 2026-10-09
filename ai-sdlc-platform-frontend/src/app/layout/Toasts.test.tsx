import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useUiStore } from "@/store/ui";
import { Toasts } from "./Toasts";

/**
 * A notice is read out as it arrives, and an error stays until it is
 * dismissed: errors went after four seconds, often unread, nothing announced
 * any notice, and the close button had no name.
 */
beforeEach(() => {
  vi.useFakeTimers();
  useUiStore.setState({ toasts: [] });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const raise = (toast: Parameters<ReturnType<typeof useUiStore.getState>["addToast"]>[0]) =>
  act(() => useUiStore.getState().addToast(toast));

describe("the notices", () => {
  it("reads an error out at once and keeps it until it is dismissed", () => {
    render(<Toasts />);
    raise({ type: "error", title: "Saving failed", message: "The server refused it." });

    expect(within(screen.getByRole("alert")).getByText("Saving failed")).toBeTruthy();
    act(() => vi.advanceTimersByTime(60_000));
    expect(screen.queryByText("Saving failed")).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("Saving failed")).toBeNull();
  });

  it("reads a success out politely and lets it go on its own", () => {
    render(<Toasts />);
    raise({ type: "success", title: "Photo updated" });

    expect(within(screen.getByRole("status")).getByText("Photo updated")).toBeTruthy();
    act(() => vi.advanceTimersByTime(4_000));
    expect(screen.queryByText("Photo updated")).toBeNull();
  });

  it("shows the same notice raised twice once", () => {
    render(<Toasts />);
    raise({ type: "error", title: "Cannot reach the server" });
    raise({ type: "error", title: "Cannot reach the server" });

    expect(screen.getAllByText("Cannot reach the server")).toHaveLength(1);
  });
});
