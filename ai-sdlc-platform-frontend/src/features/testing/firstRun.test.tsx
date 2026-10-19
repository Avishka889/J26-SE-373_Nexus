import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { testingApi } from "./api";
import type { TestSnapshot } from "./api/types";
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

const at = (secondsAgo: number) => new Date(Date.now() - secondsAgo * 1000).toISOString();

/** The run the server records the moment Run tests is pressed. */
function firstRun(state: "running" | "failed", error: string | null = null): TestSnapshot["run"] {
  return {
    id: "run-1",
    state,
    version: 1,
    model: "deepseek:deepseek-flash",
    thinking: "disabled",
    startedAt: at(90),
    finishedAt: state === "failed" ? at(30) : null,
    stoppedAt: state === "failed" ? "test-generation" : null,
    error,
  };
}

/** NexusPay, whose code review approved its build, on the snapshot given. */
async function renderWith(snapshot: TestSnapshot) {
  vi.spyOn(testingApi, "getTesting").mockResolvedValue(snapshot);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/projects/p1/testing"]}>
        <Routes>
          <Route path="/projects/:projectId/testing" element={<TestingSecurity />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * Reported from the live run of 2026-10-18. The server counts a test version
 * only once Test Generation writes its report, so a project's first run sits
 * at version 0 while it works, four and a half minutes on that run. The page
 * read version 0 as "not started" and kept offering Run tests, saying nothing
 * runs until you start it, over a run that had started.
 */
describe("a project's first test run", () => {
  it("shows its stages while it works, before it has a test version", async () => {
    // A project no run has touched: version 0, no run, nothing generating.
    const untouched = await testingApi.getTesting("p2");
    await renderWith({
      ...untouched,
      run: firstRun("running"),
      stages: Object.fromEntries(
        Object.entries(untouched.stages).map(([id, stage]) => [
          id,
          { ...stage, status: id === "test-review" ? "pending" : "generating" },
        ]),
      ) as TestSnapshot["stages"],
    });

    expect(
      await screen.findByText(/^Working on Test Generation, 1m \d+s so far$/, undefined, {
        timeout: 5000,
      }),
    ).toBeTruthy();
    expect(screen.queryByText(/Testing has not started/)).toBeNull();
  }, 15_000);

  it("says why it stopped when it stopped before writing anything", async () => {
    const untouched = await testingApi.getTesting("p2");
    await renderWith({
      ...untouched,
      run: firstRun("failed", "the workspace would not install"),
      stages: {
        ...untouched.stages,
        "test-generation": { ...untouched.stages["test-generation"], status: "failed" },
      },
    });

    expect(
      await screen.findByText("The last run stopped before it finished", undefined, {
        timeout: 5000,
      }),
    ).toBeTruthy();
    expect(screen.getByText(/The workspace would not install\./)).toBeTruthy();
    expect(screen.queryByText(/Testing has not started/)).toBeNull();
  }, 15_000);

  it("is still offered on a project no run has touched", async () => {
    await renderWith(await testingApi.getTesting("p2"));

    expect(
      await screen.findByText(/^Testing has not started for/, undefined, { timeout: 5000 }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: /Run tests/ })).toBeTruthy();
  }, 15_000);
});
