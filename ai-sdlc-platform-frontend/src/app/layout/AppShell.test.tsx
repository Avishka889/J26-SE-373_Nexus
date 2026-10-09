import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell } from "./AppShell";

// jsdom has no matchMedia, and the sidebar asks it for the viewport width.
beforeAll(() => {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function Broken(): never {
  throw new Error("snapshot.stages is undefined");
}

/**
 * The shell outlives a page that fails to render.
 *
 * The only boundary was the root one, so one phase's render error replaced the
 * sidebar, the top bar and every route with a sentence.
 */
describe("the shell", () => {
  it("keeps its navigation when the page inside it fails", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/projects/p_1/testing"]}>
          <AppShell>
            <Broken />
          </AppShell>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByRole("alert").textContent).toContain("This page hit a problem");
    expect(screen.getAllByText("Projects").length).toBeGreaterThan(0);
  });
});
