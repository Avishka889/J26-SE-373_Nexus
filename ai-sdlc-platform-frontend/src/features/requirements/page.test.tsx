import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Project } from "@/types/project";
import { hydrateProjects, useProject } from "@/entities/project";
import { useUiStore } from "@/store/ui";
import { useDesignSnapshot } from "./hooks/useDesign";
import { RequirementsPage } from "./page";

// Explicit because this suite runs without vitest's globals, which is what
// Testing Library's own automatic cleanup hooks itself onto.
afterEach(cleanup);

/**
 * The run can rename the project, and only the design snapshot knows it did.
 *
 * The page's job is to notice and refill the projects store, which is what the
 * shell header, the sidebar and the wireframe player's breadcrumb read. That
 * effect is the only new behavioural logic this feature put in a component, and
 * its live path never runs on fixtures, so this is the only thing that can hold
 * it.
 *
 * Both seams are mocked at the import boundary rather than driven through a
 * real query and a real store: the effect is a comparison between two values
 * and a call, and giving it those two values directly is what lets a test say
 * "these disagreed and nothing happened".
 */
vi.mock("@/entities/project", () => ({
  hydrateProjects: vi.fn(() => Promise.resolve()),
  useProject: vi.fn(),
}));

const started = vi.hoisted(() => ({ mutate: vi.fn(), idle: false }));

vi.mock("./hooks/useDesign", () => ({
  useDesignSnapshot: vi.fn(),
  useDesignMutations: () => ({
    // Not idle unless a test says so, so the sibling effect that auto-starts a
    // run on carried text stays out of the way of the rename tests.
    startDesignRun: { isIdle: started.idle, isPending: false, mutate: started.mutate },
  }),
}));

// The two screens the page can show are not under test, and rendering either
// for real would drag a query client and a dozen panels in with it.
vi.mock("./components/RequirementsInput", () => ({
  // A button standing in for the composer, so a test can submit it.
  RequirementsInput: ({ onSubmit }: { onSubmit: (text: string, files: string[]) => void }) => (
    <button type="button" data-testid="input" onClick={() => onSubmit("Track movies.", [])}>
      Start
    </button>
  ),
}));
vi.mock("./components/DesignWorkspace", () => ({
  DesignWorkspace: () => <div data-testid="workspace" />,
}));

const PROVISIONAL = "Build a web application for FOMMP (Farmer Organi…";
const TITLED = "FOMMP Platform";

function projectNamed(name: string): Project {
  return {
    id: "p1",
    name,
    description: "Build a web application for FOMMP.",
    status: "analyzing",
    createdAt: "2026-08-15T09:00:00.000Z",
    updatedAt: "2026-08-15T09:00:00.000Z",
    requirementText: "Build a web application for FOMMP.",
    requirementChat: [],
    files: [],
    reqPhase: "requirements",
    progress: 10,
    techStack: [],
    color: "blue",
  };
}

/** A snapshot as the page reads it: the app name, and whether a run has begun. */
function snapshotNamed(appName: string): ReturnType<typeof useDesignSnapshot> {
  return {
    data: { appName, requirementsVersion: 1 },
    isPending: false,
  } as unknown as ReturnType<typeof useDesignSnapshot>;
}

function pendingSnapshot(): ReturnType<typeof useDesignSnapshot> {
  return { data: undefined, isPending: true } as unknown as ReturnType<typeof useDesignSnapshot>;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/projects/p1/requirements"]}>
      <Routes>
        <Route path="/projects/:projectId/requirements" element={<RequirementsPage />} />
        {/* The page redirects here when the project is not in the store. */}
        <Route path="*" element={null} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RequirementsPage, picking up a rename", () => {
  beforeEach(() => {
    vi.mocked(hydrateProjects).mockClear();
  });

  it("refetches the projects when the run's title and the stored name disagree", () => {
    vi.mocked(useProject).mockReturnValue(projectNamed(PROVISIONAL));
    vi.mocked(useDesignSnapshot).mockReturnValue(snapshotNamed(TITLED));

    renderPage();

    expect(hydrateProjects).toHaveBeenCalledTimes(1);
  });

  it("does not refetch when the two names agree", () => {
    // The steady state, and the one every poll after the first lands in: this
    // firing here would be a refetch every 1.2 seconds for the whole run.
    vi.mocked(useProject).mockReturnValue(projectNamed(TITLED));
    vi.mocked(useDesignSnapshot).mockReturnValue(snapshotNamed(TITLED));

    renderPage();

    expect(hydrateProjects).not.toHaveBeenCalled();
  });

  it("does not refetch before the snapshot has arrived", () => {
    vi.mocked(useProject).mockReturnValue(projectNamed(PROVISIONAL));
    vi.mocked(useDesignSnapshot).mockReturnValue(pendingSnapshot());

    renderPage();

    expect(hydrateProjects).not.toHaveBeenCalled();
  });

  it("does not refetch before the project has arrived", () => {
    // A deep link rendered before the store is filled. Without the guard this
    // would refetch on every such render, since an absent name never matches.
    vi.mocked(useProject).mockReturnValue(undefined);
    vi.mocked(useDesignSnapshot).mockReturnValue(snapshotNamed(TITLED));

    renderPage();

    expect(hydrateProjects).not.toHaveBeenCalled();
  });

  it("does not refetch again once the refetch has landed", () => {
    // The loop safety the effect's comment claims: refetching is what removes
    // the disagreement, so the next poll sees two equal names and stops. This
    // is the same render with the store now answering with the new name.
    vi.mocked(useProject).mockReturnValue(projectNamed(PROVISIONAL));
    vi.mocked(useDesignSnapshot).mockReturnValue(snapshotNamed(TITLED));

    const { rerender } = renderPage();
    expect(hydrateProjects).toHaveBeenCalledTimes(1);

    vi.mocked(useProject).mockReturnValue(projectNamed(TITLED));
    rerender(
      <MemoryRouter initialEntries={["/projects/p1/requirements"]}>
        <Routes>
          <Route path="/projects/:projectId/requirements" element={<RequirementsPage />} />
          <Route path="*" element={null} />
        </Routes>
      </MemoryRouter>,
    );

    expect(hydrateProjects).toHaveBeenCalledTimes(1);
  });
});

/**
 * A design that could not be read is not a project with no design.
 *
 * With the first read failed, TanStack Query reports the query as neither
 * pending nor holding data, so the page took "no version yet" and showed the
 * start screen: "What should this project do?" over a project that had a
 * design, and submitting it rewrote the stored brief without starting anything.
 */
describe("RequirementsPage, when the design could not be read", () => {
  it("says so with a retry, and does not offer to start the project again", () => {
    vi.mocked(useProject).mockReturnValue(projectNamed(TITLED));
    vi.mocked(useDesignSnapshot).mockReturnValue({
      data: undefined,
      isPending: false,
      isError: true,
      error: new Error("Cannot reach the server. Check that it is running, then try again."),
      refetch: vi.fn(() => Promise.resolve()),
    } as unknown as ReturnType<typeof useDesignSnapshot>);

    renderPage();

    expect(screen.getByRole("alert").textContent).toContain("Cannot reach the server");
    expect(screen.queryByTestId("input")).toBeNull();
  });
});

/**
 * Entering the requirements opens the design with the conversation closed: the
 * run fills the stages first, and the conversation opens from its toggle when
 * there is something to answer. Open by default, it took a third of the width
 * from the stages the moment a project began.
 */
describe("RequirementsPage, entering the requirements", () => {
  it("starts the design with the conversation closed", () => {
    useUiStore.setState({ conversationOpen: true });
    vi.mocked(useProject).mockReturnValue({ ...projectNamed(TITLED), requirementText: "" });
    vi.mocked(useDesignSnapshot).mockReturnValue({
      data: { appName: TITLED, requirementsVersion: 0 },
      isPending: false,
    } as unknown as ReturnType<typeof useDesignSnapshot>);
    started.mutate.mockClear();

    renderPage();
    fireEvent.click(screen.getByTestId("input"));

    expect(started.mutate).toHaveBeenCalledWith({ text: "Track movies.", files: [] });
    expect(useUiStore.getState().conversationOpen).toBe(false);
  });

  it("starts a project that arrived with its text with the conversation closed too", () => {
    useUiStore.setState({ conversationOpen: true });
    vi.mocked(useProject).mockReturnValue({ ...projectNamed(TITLED), requirementText: "Track movies." });
    vi.mocked(useDesignSnapshot).mockReturnValue({
      data: { appName: TITLED, requirementsVersion: 0 },
      isPending: false,
    } as unknown as ReturnType<typeof useDesignSnapshot>);
    started.mutate.mockClear();
    started.idle = true;

    try {
      renderPage();
    } finally {
      started.idle = false;
    }

    expect(started.mutate).toHaveBeenCalledWith({ text: "Track movies.", files: [] });
    expect(useUiStore.getState().conversationOpen).toBe(false);
  });
});
