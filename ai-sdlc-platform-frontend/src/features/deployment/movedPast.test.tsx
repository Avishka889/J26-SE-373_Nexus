import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { deploymentApi } from "./api";
import { DeploymentDependency } from "./page";

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

const WAITING_RUN = {
  id: "run-1",
  state: "awaiting_gate" as const,
  model: "deepseek:deepseek-flash",
  thinking: "disabled",
  startedAt: "2026-10-04T09:00:00+00:00",
  finishedAt: null,
  stoppedAt: null,
  error: null,
};

/**
 * A deployment review waiting while newer code was tested is of an analysis of
 * code that may no longer ship. Its approval was refused, requesting changes
 * analysed the older code again, and analysing again was off while it waited.
 * Newer code still waiting for its tests is no such move: the analysed code is
 * what may ship, and the review stays open.
 */
describe("a deployment review the code has moved past", () => {
  async function show(tested: "current" | "older") {
    const base = await deploymentApi.getDeployment("p4");
    const current = base.deployedCodeVersion + 1;
    vi.spyOn(deploymentApi, "getDeployment").mockResolvedValue({
      ...base,
      gate: { ...base.gate, decision: null },
      stages: {
        ...base.stages,
        "deployment-review": {
          ...base.stages["deployment-review"],
          status: "complete",
          generatedFromVersion: base.deployVersion,
        },
      },
      codeVersion: current,
      // As the server reads it: stale once the newer code's tests are approved.
      codeMovedOn: tested === "current",
      approvedTestedCodeVersion: tested === "current" ? current : base.deployedCodeVersion,
      run: { ...WAITING_RUN, version: base.deployVersion },
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/projects/p4/deployment"]}>
          <Routes>
            <Route path="/projects/:projectId/deployment" element={<DeploymentDependency />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    return current;
  }

  it("offers analysing again once the newer code is tested, and no changes", async () => {
    const current = await show("current");

    const said = await screen.findAllByText(
      new RegExp(`Analyse the updates again to analyse version ${current}`),
    );
    expect(said.length).toBeGreaterThanOrEqual(1);
    const again = screen.getByRole("button", { name: /Analyse updates again/ }) as HTMLButtonElement;
    expect(again.disabled).toBe(false);
    const request = screen.getByRole("button", { name: /Request changes/ }) as HTMLButtonElement;
    expect(request.disabled).toBe(true);
  });

  it("keeps the review open while the newer code waits for its tests", async () => {
    const current = await show("older");

    await screen.findByText(new RegExp(`Code version ${current} is newer and waits for its own tests`));
    expect(screen.getByRole("button", { name: /Open Testing & Security/ })).toBeTruthy();
    const again = screen.getByRole("button", { name: /Analyse updates again/ }) as HTMLButtonElement;
    expect(again.disabled).toBe(true);
    expect(again.title).toBe("Decide the waiting review first");
    const request = screen.getByRole("button", { name: /Request changes/ }) as HTMLButtonElement;
    expect(request.disabled).toBe(false);
  });
});
