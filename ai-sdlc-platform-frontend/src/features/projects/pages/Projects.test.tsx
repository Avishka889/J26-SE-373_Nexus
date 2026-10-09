import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const state = vi.hoisted(() => ({
  load: { status: "failed", error: "Cannot reach the server. Check that it is running, then try again." } as {
    status: string;
    error: string | null;
  },
  list: [] as unknown[],
  hydrate: vi.fn(() => Promise.reject(new Error("still down"))),
  remove: vi.fn((_id: string) => Promise.resolve()),
}));

vi.mock("@/entities/project", async (original) => ({
  ...(await original<typeof import("@/entities/project")>()),
  useProjectsLoad: () => state.load,
  hydrateProjects: state.hydrate,
}));

vi.mock("../hooks", () => ({
  useProjectsList: () => state.list,
  useProjectMutations: () => ({ deleteProjectSync: state.remove }),
}));

const { Projects } = await import("./Projects");

afterEach(cleanup);

/**
 * An unread list is not an empty one.
 *
 * A failed read showed "No projects yet" and a button inviting a new project,
 * which is how duplicates are made while the server restarts.
 */
describe("the project list when the server could not be read", () => {
  it("says so with a retry, and does not claim there are no projects", () => {
    render(
      <MemoryRouter>
        <Projects />
      </MemoryRouter>,
    );

    expect(screen.getByRole("alert").textContent).toContain("Cannot reach the server");
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(screen.queryByText("No projects yet")).toBeNull();
  });
});

/**
 * A project whose current phase's run stopped read as nothing was wrong: its
 * status named the phase and nothing said the run there had stopped.
 */
describe("a project whose run stopped", () => {
  it("says so beside its status", () => {
    state.load = { status: "loaded", error: null };
    state.list = [
      {
        id: "p1",
        name: "Ledger",
        description: "",
        status: "design",
        runStopped: true,
        createdAt: "2026-10-03T09:00:00Z",
        updatedAt: "2026-10-03T09:00:00Z",
        requirementText: "Someone records a payment.",
        requirementChat: [],
        files: [],
        reqPhase: "requirements",
        progress: 3,
        phaseProgress: { design: 10, code: 0, testing: 0, deployment: 0 },
        techStack: [],
        color: "#3b82f6",
      },
    ];
    render(
      <MemoryRouter>
        <Projects />
      </MemoryRouter>,
    );

    expect(screen.getAllByText("Run stopped").length).toBeGreaterThan(0);
  });
});

/**
 * Statuses move while the reader is elsewhere, and the list was read once, at
 * sign-in: Home and Projects kept showing them as they were.
 */
describe("the project list when it opens", () => {
  it("is read again", () => {
    state.load = { status: "loaded", error: null };
    state.hydrate.mockClear();
    render(
      <MemoryRouter>
        <Projects />
      </MemoryRouter>,
    );

    expect(state.hydrate).toHaveBeenCalledTimes(1);
  });
});

/**
 * Delete said "Project deleted" before the server answered, so a refusal (a
 * run or a release still going) read as done; and its warning promised that
 * everything generated would go, which the repository and the deployments do not.
 */
describe("deleting a project", () => {
  it("says it is deleted only once the server has, and says so when it refused", async () => {
    const { useUiStore } = await import("@/store/ui");
    useUiStore.setState({ toasts: [] });
    state.load = { status: "loaded", error: null };
    state.list = [
      {
        id: "p1",
        name: "Ledger",
        description: "",
        status: "deploy",
        progress: 75,
        updatedAt: "2026-10-03T09:12:00Z",
        createdAt: "2026-10-01T09:12:00Z",
        techStack: [],
        color: "#2563eb",
      },
    ];
    state.remove.mockImplementationOnce(() =>
      Promise.reject(new Error("A Deployment run is in progress on this project.")),
    );
    render(
      <MemoryRouter>
        <Projects />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getAllByRole("button", { name: "Delete Ledger" })[0]);
    const dialog = screen.getByRole("alertdialog");
    expect(dialog.textContent).toContain("GitHub repository and any Vercel or Render deployments are not touched");
    // What does go with it, which the server removes: its release on this machine.
    expect(dialog.textContent).toContain("Its release on this machine goes with it");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete project" }));

    await waitFor(() =>
      expect(useUiStore.getState().toasts.map((t) => t.title)).toEqual(["Ledger was not deleted"]),
    );
    expect(useUiStore.getState().toasts[0].message).toContain("in progress");
  });
});

/**
 * Eighty projects with no filter, no sort and no way to delete more than one;
 * cards that opened on click alone, so not by keyboard; and a delete button
 * that appeared only on hover, and in the list view not at all.
 */
describe("triaging the projects", () => {
  const listed = (name: string, extra: Record<string, unknown> = {}) => ({
    id: name.toLowerCase(),
    name,
    description: "",
    status: "design",
    progress: 10,
    createdAt: "2026-10-01T09:12:00Z",
    updatedAt: "2026-10-01T09:12:00Z",
    requirementText: "",
    techStack: [],
    color: "#2563eb",
    ...extra,
  });

  const page = () =>
    render(
      <MemoryRouter>
        <Projects />
      </MemoryRouter>,
    );

  it("opens each project from a link, and shows only those asked for", () => {
    state.load = { status: "loaded", error: null };
    state.list = [listed("Ledger"), listed("Cargo", { runStopped: true })];
    page();

    expect(screen.getByRole("link", { name: "Ledger" }).getAttribute("href")).toBe("/projects/ledger/requirements");
    fireEvent.change(screen.getByRole("combobox", { name: "Show" }), { target: { value: "stopped" } });

    expect(screen.queryByRole("link", { name: "Ledger" })).toBeNull();
    expect(screen.getByRole("link", { name: "Cargo" })).toBeTruthy();
  });

  it("deletes the selected projects, each answered, and says which were refused", async () => {
    const { useUiStore } = await import("@/store/ui");
    useUiStore.setState({ toasts: [] });
    state.load = { status: "loaded", error: null };
    state.list = [listed("Ledger"), listed("Cargo"), listed("Atlas")];
    state.remove.mockReset();
    state.remove.mockImplementation((id: string) =>
      id === "cargo" ? Promise.reject(new Error("A release is in progress on this project.")) : Promise.resolve(),
    );
    page();

    fireEvent.click(screen.getByRole("button", { name: "Show as a list" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Ledger" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Cargo" }));
    expect(screen.getByRole("button", { name: "Delete Atlas" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Delete selected" }));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete 2 projects" }));

    await waitFor(() =>
      expect(useUiStore.getState().toasts.map((t) => t.title)).toEqual([
        "1 project deleted",
        "1 project was not deleted",
      ]),
    );
    expect(state.remove.mock.calls.map(([id]) => id)).toEqual(["ledger", "cargo"]);
    expect(useUiStore.getState().toasts[1].message).toContain("Cargo: A release is in progress");
  });
});
