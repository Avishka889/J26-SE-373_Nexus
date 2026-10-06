import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const state = vi.hoisted(() => ({ list: [] as unknown[] }));

vi.mock("@/entities/project", async (original) => ({
  ...(await original<typeof import("@/entities/project")>()),
  useProjectsLoad: () => ({ status: "loaded", error: null }),
  getProjectsLoad: () => ({ status: "idle", error: null }),
  hydrateProjects: vi.fn(() => Promise.resolve()),
}));

vi.mock("@/entities/settings", async (original) => ({
  ...(await original<typeof import("@/entities/settings")>()),
  useSettings: () => ({ profile: { name: "Sam Reader" } }),
}));

vi.mock("../hooks", () => ({
  useProjectsList: () => state.list,
  useCreateFromPrompt: () => vi.fn(),
}));

const { Home } = await import("./Home");

afterEach(cleanup);

/**
 * The strip on a project's card is its four phases. It was coloured from the
 * overall average, so a project in Code read as Design in progress.
 */
describe("a project card's four-phase strip", () => {
  it("shows each phase from its own progress, in words as well as colour", () => {
    state.list = [
      {
        id: "p1",
        name: "Ledger",
        description: "",
        status: "code",
        createdAt: "2026-10-03T09:00:00Z",
        updatedAt: "2026-10-03T09:00:00Z",
        requirementText: "Someone records a payment.",
        requirementChat: [],
        files: [],
        reqPhase: "requirements",
        progress: 25,
        phaseProgress: { design: 100, code: 0, testing: 0, deployment: 0 },
        techStack: [],
        color: "#3b82f6",
      },
    ];

    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <Home />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(
      screen.getByRole("img", {
        name: "Design complete, Code not started, Testing not started, Deployment not started",
      }),
    ).toBeTruthy();
  });
});
