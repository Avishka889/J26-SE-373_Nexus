import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const state = vi.hoisted(() => ({
  load: { status: "loading", error: null } as { status: string; error: string | null },
}));

vi.mock("@/entities/project", async (original) => ({
  ...(await original<typeof import("@/entities/project")>()),
  useProjectsLoad: () => state.load,
  getProjectsLoad: () => state.load,
  hydrateProjects: vi.fn(() => Promise.resolve()),
}));

vi.mock("../hooks", async (original) => ({
  ...(await original<typeof import("../hooks")>()),
  useProjectsList: () => [],
  useCreateFromPrompt: () => vi.fn(),
}));

const { Home } = await import("./Home");
const { Projects } = await import("./Projects");

afterEach(cleanup);

const show = (page: "home" | "projects") =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>{page === "home" ? <Home /> : <Projects />}</MemoryRouter>
    </QueryClientProvider>,
  );

/**
 * While the list was read the page showed one small spinner where the cards
 * go, which on Home sat below the fold and read as an empty workspace.
 */
describe("a project list that is still being read", () => {
  for (const page of ["home", "projects"] as const) {
    it(`draws the cards' places on ${page}, and does not say there are none`, () => {
      state.load = { status: "loading", error: null };
      show(page);

      const loading = screen.getByRole("status", { name: "Loading your projects" });
      expect(loading.querySelectorAll("[data-skeleton-card]").length).toBeGreaterThanOrEqual(3);
      expect(screen.queryByText("No projects yet")).toBeNull();
    });

    it(`says there are none on ${page} once the list is read and empty`, () => {
      state.load = { status: "loaded", error: null };
      show(page);

      expect(screen.queryByRole("status", { name: "Loading your projects" })).toBeNull();
      expect(screen.getByText("No projects yet")).toBeTruthy();
    });
  }
});
