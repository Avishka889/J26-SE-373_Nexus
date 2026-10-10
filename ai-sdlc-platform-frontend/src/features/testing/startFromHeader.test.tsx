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

/** A project no test run has touched, under the project the route names. */
async function untouchedAt(projectId: string) {
  vi.spyOn(testingApi, "getTesting").mockResolvedValue(await testingApi.getTesting("p2"));
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[`/projects/${projectId}/testing`]}>
        <Routes>
          <Route path="/projects/:projectId/testing" element={<TestingSecurity />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText(/^Testing has not started for/, undefined, { timeout: 5000 });
}

/**
 * Code Generation's first run starts from its header. This phase's started
 * from the foot of its not-started card, below the six steps it describes.
 */
describe("the first test run", () => {
  it("is offered once, from the header, when the code review approved a build", async () => {
    // NexusPay's status says its code review approved a build.
    await untouchedAt("p1");

    const starts = screen.getAllByRole("button", { name: "Run tests" });
    expect(starts).toHaveLength(1);
    expect(starts[0].closest("[data-run-controls]")).not.toBeNull();
  }, 15_000);

  it("is not offered before the code review approved a build", async () => {
    // MediTrack is still in Code Generation.
    await untouchedAt("p2");

    expect(screen.queryByRole("button", { name: "Run tests" })).toBeNull();
    expect(screen.getByRole("button", { name: /Open Code Generation/ })).toBeTruthy();
  }, 15_000);
});
