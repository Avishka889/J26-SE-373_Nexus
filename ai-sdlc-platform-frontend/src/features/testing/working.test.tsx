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
 * Reported from the live run: Test Generation waited three minutes on the model,
 * every stage showed a spinner, and nothing on the page said which stage was
 * working or for how long.
 */
describe("the Testing page while a run works", () => {
  // The whole page renders here, which once took longer than the default five
  // seconds beside every other file's tests, though it passed alone and the next
  // whole run.
  it("names the stage the run is working on, timed from when the stage before it finished", async () => {
    const base = await testingApi.getTesting("p1");
    const now = Date.now();
    const at = (secondsAgo: number) => new Date(now - secondsAgo * 1000).toISOString();
    vi.spyOn(testingApi, "getTesting").mockResolvedValue({
      ...base,
      codeMovedOn: false,
      run: {
        id: "run-1",
        state: "running",
        version: base.testVersion,
        model: "deepseek:deepseek-flash",
        thinking: "disabled",
        startedAt: at(300),
        finishedAt: null,
        stoppedAt: null,
        error: null,
      },
      stages: Object.fromEntries(
        Object.entries(base.stages).map(([id, stage]) => [
          id,
          id === "test-generation"
            ? { ...stage, status: "complete", generatedAt: at(65) }
            : id === "test-review"
              ? { ...stage, status: "pending" }
              : { ...stage, status: "generating" },
        ]),
      ) as typeof base.stages,
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

    expect(
      await screen.findByText(/^Working on Test Run, 1m \d+s so far$/, undefined, { timeout: 5000 }),
    ).toBeTruthy();
  }, 15_000);
});
