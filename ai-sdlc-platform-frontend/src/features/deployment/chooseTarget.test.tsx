import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { choose } from "@/shared/testing/choose";
import { deploymentApi } from "./api";
import type { DeploySnapshot } from "./api/types";
import { DeploymentDependency } from "./page";

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

const TARGETS = [
  { id: "local" as const, label: "This machine, in containers", usable: true, reason: "" },
  { id: "cloud" as const, label: "Vercel and Render, through GitHub Actions", usable: true, reason: "" },
];

/**
 * Where to release is saved on the server, which answers with the whole phase
 * composed again. The dropdown showed the old choice until that answer came,
 * two or three seconds on a hosted database, and read as a click that missed.
 */
// The whole page, rendered and driven: slow beside a full suite, where the
// default five seconds ran out once.
describe("choosing where to release", { timeout: 20_000 }, () => {
  async function show() {
    const base = await deploymentApi.getDeployment("p4");
    vi.spyOn(deploymentApi, "getDeployment").mockResolvedValue({ ...base, releaseTarget: "local" });
    vi.spyOn(deploymentApi, "listTargets").mockResolvedValue(TARGETS);
    let settle!: { resolve: (s: DeploySnapshot) => void; reject: (e: Error) => void };
    const save = vi.spyOn(deploymentApi, "chooseTarget").mockImplementation(
      () => new Promise<DeploySnapshot>((resolve, reject) => (settle = { resolve, reject })),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/projects/p4/deployment?stage=deployment-review"]}>
          <Routes>
            <Route path="/projects/:projectId/deployment" element={<DeploymentDependency />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    // The header's is off while a review waits; the review has its own.
    await waitFor(() => expect(screen.getAllByRole("combobox", { name: /release to/i })).toHaveLength(2));
    const [header, review] = screen.getAllByRole("combobox", { name: /release to/i });
    await waitFor(() => expect(review.textContent).toBe("This machine, in containers"));
    return { base, header, review, save, settle: () => settle };
  }

  it("shows the choice at once, while the server is still being told", async () => {
    const { header, review, save } = await show();
    await choose(review, /Vercel and Render/);

    expect(save).toHaveBeenCalledTimes(1);
    expect(review.textContent).toBe("Vercel and Render, through GitHub Actions");
    // Both dropdowns are the one choice.
    expect(header.textContent).toBe("The cloud");
  });

  it("keeps the choice once the server has it", async () => {
    const { base, review, settle } = await show();
    await choose(review, /Vercel and Render/);
    settle().resolve({ ...base, releaseTarget: "cloud" });

    await waitFor(() => expect(review.hasAttribute("data-disabled")).toBe(false));
    expect(review.textContent).toBe("Vercel and Render, through GitHub Actions");
  });

  it("goes back to what the server holds when the save is refused, and says so", async () => {
    const { useUiStore } = await import("@/store/ui");
    useUiStore.setState({ toasts: [] });
    const { review, settle } = await show();
    await choose(review, /Vercel and Render/);
    await waitFor(() => expect(review.textContent).toBe("Vercel and Render, through GitHub Actions"));
    settle().reject(new Error("a deployment run is analysing"));

    await waitFor(() => expect(review.textContent).toBe("This machine, in containers"));
    expect(useUiStore.getState().toasts.map((t) => t.message)).toContain("a deployment run is analysing");
  });
});
