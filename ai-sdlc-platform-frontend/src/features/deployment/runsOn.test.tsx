import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { PhaseModel } from "@/entities/settings";
import { deploymentApi } from "./api";
import { DeploymentDependency } from "./page";

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
 * analyses again in the run that waits there, at the level it started at, so
 * the box names that run's level and the next run's beside it.
 */
describe("the Deployment chat box", () => {
  async function showWithReview(waiting: boolean) {
    const base = await deploymentApi.getDeployment("p4");
    const review = base.stages["deployment-review"];
    vi.spyOn(deploymentApi, "getDeployment").mockResolvedValue({
      ...base,
      gate: { ...base.gate, decision: null },
      stages: {
        ...base.stages,
        "deployment-review": {
          ...review,
          status: waiting ? "complete" : "pending",
          generatedFromVersion: base.deployVersion,
        },
      },
      run: {
        id: "run-1",
        state: waiting ? "awaiting_gate" : "done",
        version: base.deployVersion,
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
        phase: "Deployment",
        key: "deployment",
        model: FLASH,
        thinking: "high",
        thinkingChosen: true,
        thinkingApplies: true,
      },
    ];
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/projects/p4/deployment"]}>
          <Routes>
            <Route path="/projects/:projectId/deployment" element={<DeploymentDependency />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("names the waiting run's level while a review waits, and the next run's beside it", async () => {
    await showWithReview(true);

    expect(
      await screen.findByText(`This run: ${FLASH}, thinking off. Next run: thinking on, high effort.`),
    ).toBeTruthy();
  });

  it("names the next run's once nothing waits", async () => {
    await showWithReview(false);

    expect(await screen.findByText(`Next run: ${FLASH}, thinking on, high effort.`)).toBeTruthy();
  });
});
