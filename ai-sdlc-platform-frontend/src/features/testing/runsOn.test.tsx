import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { PhaseModel } from "@/entities/settings";
import { testingApi } from "./api";
import { TestingSecurity } from "./page";

const phases = vi.hoisted(() => ({ models: [] as PhaseModel[] }));

vi.mock("@/entities/settings/models", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/entities/settings/models")>()),
  phaseModels: vi.fn(async () => phases.models),
}));

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

const FLASH = "deepseek:deepseek-flash";

/**
 * The chat box says what a send runs on. A request for changes at the review
 * runs the tests again in the run that waits there, at the level it started
 * at, so the box names that run's level and the next run's beside it.
 */
// The whole page, rendered: slow beside a full suite, where the default five
// seconds ran out twice in one evening (it passes alone in two).
describe("the Testing chat box", { timeout: 20_000 }, () => {
  async function showWithRun(state: "awaiting_gate" | "done") {
    const base = await testingApi.getTesting("p1");
    vi.spyOn(testingApi, "getTesting").mockResolvedValue({
      ...base,
      codeMovedOn: false,
      run: {
        id: "run-1",
        state,
        version: base.testVersion,
        model: FLASH,
        thinking: "disabled",
        startedAt: "2026-10-04T09:00:00+00:00",
        finishedAt: null,
        stoppedAt: null,
        error: null,
      },
    });
    phases.models = [
      {
        phase: "Testing and Security",
        key: "testing",
        model: FLASH,
        thinking: "high",
        thinkingChosen: true,
        thinkingApplies: true,
      },
    ];
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

  it("names the waiting run's level while a review waits, and the next run's beside it", async () => {
    await showWithRun("awaiting_gate");

    expect(
      await screen.findByText(`This run: ${FLASH}, thinking off. Next run: thinking on, high effort.`),
    ).toBeTruthy();
  });

  it("names the next run's once nothing waits", async () => {
    await showWithRun("done");

    expect(await screen.findByText(`Next run: ${FLASH}, thinking on, high effort.`)).toBeTruthy();
  });
});
