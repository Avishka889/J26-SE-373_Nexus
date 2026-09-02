import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const state = vi.hoisted(() => ({
  load: { status: "failed", error: "Cannot reach the server. Check that it is running, then try again." } as {
    status: "loading" | "loaded" | "failed";
    error: string | null;
  },
}));

vi.mock("@/entities/settings", async (original) => ({
  ...(await original<typeof import("@/entities/settings")>()),
  useConnections: () => [],
  useConnectionsLoad: () => state.load,
}));

const { GitTab } = await import("./GitTab");

afterEach(cleanup);

/**
 * Until the connections were read every provider said "Not connected" and
 * offered a token field, and a read that failed said nothing: both invited a
 * new token over one that worked.
 */
describe("a provider whose connections were not read", () => {
  it("says so with a retry, and offers no token field", () => {
    render(<GitTab />);

    expect(screen.getByRole("alert").textContent).toContain("could not be read");
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(document.querySelector('input[type="password"]')).toBeNull();
    expect(screen.queryByText("Not connected")).toBeNull();
  });

  it("says it is checking while the read is on its way", () => {
    state.load = { status: "loading", error: null };
    render(<GitTab />);

    expect(screen.getAllByText(/Checking\.\.\.|Reading your connections/).length).toBeGreaterThan(0);
    expect(document.querySelector('input[type="password"]')).toBeNull();
  });
});
