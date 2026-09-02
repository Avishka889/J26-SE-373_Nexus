import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const state = vi.hoisted(() => ({
  load: { status: "loading", error: null } as { status: string; error: string | null },
  project: undefined as { id: string } | undefined,
}));

vi.mock("@/entities/project", () => ({
  useProjectsLoad: () => state.load,
  useProject: () => state.project,
  hydrateProjects: vi.fn(() => Promise.resolve()),
}));

const { ProjectGuard } = await import("./ProjectGuard");

afterEach(cleanup);

function at(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/projects/:projectId/testing"
          element={
            <ProjectGuard>
              <p>The testing page</p>
            </ProjectGuard>
          }
        />
        <Route path="/projects" element={<p>The project list</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

/**
 * A deep link waits for the list, and says so when the list cannot be read.
 *
 * It rendered nothing until the list arrived, and nothing for good when the
 * read failed, since no failure was ever recorded.
 */
describe("a project page reached by its address", () => {
  it("shows a loader while the list is on its way", () => {
    state.load = { status: "loading", error: null };
    at("/projects/p_1/testing");

    expect(screen.getByRole("status")).toBeTruthy();
  });

  it("says the server cannot be reached, with a retry, when the list failed", () => {
    state.load = { status: "failed", error: "Cannot reach the server. Check that it is running, then try again." };
    at("/projects/p_1/testing");

    expect(screen.getByRole("alert").textContent).toContain("Cannot reach the server");
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("shows the page once the list has it", () => {
    state.load = { status: "loaded", error: null };
    state.project = { id: "p_1" };
    at("/projects/p_1/testing");

    expect(screen.getByText("The testing page")).toBeTruthy();
  });
});
