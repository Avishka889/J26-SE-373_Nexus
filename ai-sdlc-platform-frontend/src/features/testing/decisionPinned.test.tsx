import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { testingApi } from "./api";
import { TestingSecurity } from "./page";

// The whole page, which watches its sections scroll; jsdom has neither.
const scrollIntoView = Element.prototype.scrollIntoView;
beforeAll(() => {
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
    },
  );
  Element.prototype.scrollIntoView = () => {};
});
afterAll(() => {
  vi.unstubAllGlobals();
  Element.prototype.scrollIntoView = scrollIntoView;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/**
 * The decision bar sticks to the bottom of the stage column, as Design's and
 * Code's do. Here it was wrapped in a box of its own height, and a sticky
 * element sticks only within its parent: it sat at the end of every stage, and
 * the reader scrolled to the bottom of each to find Approve.
 */
describe("the test review's decision bar", { timeout: 20_000 }, () => {
  it("is a child of the stage column itself, which is what lets it stick", async () => {
    const base = await testingApi.getTesting("p1");
    vi.spyOn(testingApi, "getTesting").mockResolvedValue({
      ...base,
      gate: { ...base.gate, decision: null },
      run: {
        id: "run-1",
        state: "awaiting_gate",
        version: base.testVersion,
        model: "deepseek:deepseek-flash",
        thinking: "disabled",
        startedAt: "2026-10-04T09:00:00+00:00",
        finishedAt: null,
        stoppedAt: null,
        error: null,
      },
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/projects/p1/testing"]}>
          <Routes>
            <Route path="/projects/:projectId/testing" element={<TestingSecurity />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const headline = await screen.findByText(/This phase is waiting on you/);
    const bar = headline.closest(".sticky") as HTMLElement;
    const rail = document.querySelector("[data-stage-rail]") as HTMLElement;

    expect(bar).not.toBeNull();
    // The rail sticks because it is a direct child of this column; so must the bar.
    expect(bar.parentElement).toBe(rail.parentElement);
  });
});
